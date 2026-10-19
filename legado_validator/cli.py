# -*- coding: utf-8 -*-
"""命令行入口。

子命令::

    resolve    解析书源搜索规则，产出请求规格（需要 node）
    validate   在本机对书源做真实网络校验
    merge      合并多节点结果，取合集并打标签
    report     生成 Markdown 报告
    run-nodes  把校验任务分发到多个节点执行，再拉回结果合并
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

from . import config as cfg
from .merger import merge, write_outputs
from .reporter import build_report, write_report
from .validator import save_results, validate_all

PKG_ROOT = os.path.dirname(os.path.abspath(__file__))
JS_RESOLVER = os.path.join(PKG_ROOT, 'js', 'resolve.js')


def _log(msg):
    print(msg, flush=True)


def cmd_resolve(args, conf):
    if not shutil.which(conf.get('js_runtime', 'node')):
        _log('ERROR: 找不到 %s，无法解析 JS 规则' % conf.get('js_runtime', 'node'))
        return 2
    cmd = [conf.get('js_runtime', 'node'), JS_RESOLVER, args.src, args.out,
           args.kw, str(args.page)]
    _log('执行: %s' % ' '.join(cmd))
    proc = subprocess.run(cmd, cwd=os.path.dirname(os.path.abspath(args.src)) or '.')
    return proc.returncode


def cmd_validate(args, conf):
    with open(args.src, 'r', encoding='utf-8') as fh:
        sources = json.load(fh)
    with open(args.spec, 'r', encoding='utf-8') as fh:
        specs = json.load(fh)
    only = None
    if args.only:
        only = [int(x) for x in args.only.replace(' ', '').split(',') if x]
    t0 = time.time()
    results = validate_all(
        sources, specs, args.server, timeout=args.timeout, threads=args.threads,
        kw0=args.kw, keywords=conf.get('keywords'), user_agent=conf.get('user_agent'),
        only=only, progress=_log)
    save_results(results, args.out)
    counts = {}
    for r in results:
        counts[r.get('status')] = counts.get(r.get('status'), 0) + 1
    _log('server=%s total=%d 用时%.0fs' % (args.server, len(results), time.time() - t0))
    _log('状态分布: %s' % counts)
    return 0


def _load_results(specs):
    results = {}
    for item in specs:
        name, path = item.split('=', 1)
        with open(path, 'r', encoding='utf-8') as fh:
            results[name] = json.load(fh)
    return results


def cmd_merge(args, conf):
    with open(args.src, 'r', encoding='utf-8') as fh:
        sources = json.load(fh)
    results = _load_results(args.result)
    result = merge(sources, results, cn_server=args.cn_server,
                   overseas_server=args.overseas_server)
    paths = write_outputs(result, args.out_dir)
    _log('总书源: %d  保留: %d  剔除: %d  需外网: %d  实测可用: %d' % (
        len(sources), len(result['kept']), len(result['removed']),
        len(result['overseas']), len(result['verified'])))
    for key in sorted(result['stats']):
        _log('  %-22s %d' % (key, result['stats'][key]))
    for name, path in sorted(paths.items()):
        _log('  输出 %-24s %s' % (name, path))
    report = build_report(sources, result['kept'], result['removed'],
                          list(results.keys()))
    rp = write_report(report, os.path.join(args.out_dir, 'report.md'))
    _log('  输出 %-24s %s' % ('report.md', rp))
    return 0


def cmd_report(args, conf):
    with open(args.src, 'r', encoding='utf-8') as fh:
        sources = json.load(fh)
    results = _load_results(args.result)
    result = merge(sources, results, cn_server=args.cn_server,
                   overseas_server=args.overseas_server)
    report = build_report(sources, result['kept'], result['removed'],
                          list(results.keys()))
    path = write_report(report, args.out)
    _log('报告已生成: %s' % path)
    return 0


def _pack_package(dest):
    """把校验器打成 tar 包，方便投放到远端节点。"""
    tar_path = os.path.join(dest, 'legado_validator.tar.gz')
    with tarfile.open(tar_path, 'w:gz') as tar:
        tar.add(PKG_ROOT, arcname='legado_validator')
    return tar_path


def _ssh(node, command, timeout=3600):
    full = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', node, command]
    return subprocess.run(full, timeout=timeout)


def cmd_run_nodes(args, conf):
    """把 resolve+validate 任务分发到各节点执行，拉回结果后合并。"""
    servers = conf.get('servers') or []
    if not servers:
        _log('ERROR: 配置里没有 servers')
        return 2
    workdir = args.workdir
    os.makedirs(workdir, exist_ok=True)
    tar_path = _pack_package(workdir)
    remote_specs = []
    for srv in servers:
        name = srv['name']
        host = srv.get('host', name)
        _log('=== 节点 %s (%s) ===' % (name, host))
        _remote = 'mkdir -p %s && tar -xzf - -C %s' % (workdir, workdir)
        with open(tar_path, 'rb') as fh:
            subprocess.run(['ssh', '-o', 'BatchMode=yes', host, _remote],
                           stdin=fh, timeout=300)
        subprocess.run(['scp', '-q', args.src, '%s:%s/' % (host, workdir)], timeout=900)
        deps = _ssh(host, 'python3 -c "import requests" 2>&1')
        if deps.returncode != 0:
            _log('  节点 %s 缺少 requests 依赖，跳过' % name)
            continue
        _log('  分发完成，开始执行 resolve + validate ...')
        cmd = (
            'cd %s && export PATH=$HOME/opt/node-v20.18.1-linux-x64/bin:$PATH && '
            'python3 -m legado_validator resolve --src %s --out spec_%s.json --kw %s && '
            'python3 -m legado_validator validate --src %s --spec spec_%s.json '
            '--out res_%s.json --server %s --threads %d --timeout %d'
            % (workdir, os.path.basename(args.src), name, args.kw,
               os.path.basename(args.src), name, name, name, args.threads, args.timeout)
        )
        proc = _ssh(host, cmd)
        if proc.returncode != 0:
            _log('  节点 %s 执行失败' % name)
            continue
        local = os.path.join(workdir, 'res_%s.json' % name)
        subprocess.run(['scp', '-q', '%s:%s/res_%s.json' % (host, workdir, name),
                        local], timeout=900)
        remote_specs.append('%s=%s' % (name, local))
        _log('  节点 %s 完成，结果已拉回' % name)
    if not remote_specs:
        _log('ERROR: 没有任何节点产出结果')
        return 1
    args.result = remote_specs
    args.out_dir = args.out_dir
    return cmd_merge(args, conf)


def build_parser():
    p = argparse.ArgumentParser(
        prog='legado-validator',
        description='legado 书源校验器：双节点实测、剔除无效源、区分国内/海外可用性')
    p.add_argument('--config', help='配置文件路径（JSON）')
    sub = p.add_subparsers(dest='command')

    sp = sub.add_parser('resolve', help='解析搜索规则 -> 请求规格')
    sp.add_argument('--src', required=True, help='书源 JSON')
    sp.add_argument('--out', required=True, help='输出请求规格 JSON')
    sp.add_argument('--kw', default='修真', help='搜索关键词')
    sp.add_argument('--page', type=int, default=1, help='页码')
    sp.set_defaults(func=cmd_resolve)

    sp = sub.add_parser('validate', help='本机实测校验书源')
    sp.add_argument('--src', required=True)
    sp.add_argument('--spec', required=True)
    sp.add_argument('--out', required=True)
    sp.add_argument('--server', required=True, help='节点名')
    sp.add_argument('--threads', type=int, default=10)
    sp.add_argument('--timeout', type=int, default=25)
    sp.add_argument('--kw', default='修真')
    sp.add_argument('--only', help='只校验指定下标，逗号分隔')
    sp.set_defaults(func=cmd_validate)

    sp = sub.add_parser('merge', help='合并多节点结果')
    sp.add_argument('--src', required=True)
    sp.add_argument('--result', action='append', required=True,
                    help='节点名=结果文件，可重复')
    sp.add_argument('--out-dir', required=True)
    sp.add_argument('--cn-server')
    sp.add_argument('--overseas-server')
    sp.set_defaults(func=cmd_merge)

    sp = sub.add_parser('report', help='生成 Markdown 报告')
    sp.add_argument('--src', required=True)
    sp.add_argument('--result', action='append', required=True)
    sp.add_argument('--out', required=True)
    sp.add_argument('--cn-server')
    sp.add_argument('--overseas-server')
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser('run-nodes', help='分发到多节点执行并合并')
    sp.add_argument('--src', required=True)
    sp.add_argument('--out-dir', required=True)
    sp.add_argument('--workdir', default='/tmp/legado-validator')
    sp.add_argument('--kw', default='修真')
    sp.add_argument('--threads', type=int, default=10)
    sp.add_argument('--timeout', type=int, default=25)
    sp.add_argument('--cn-server')
    sp.add_argument('--overseas-server')
    sp.set_defaults(func=cmd_run_nodes)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, 'command', None):
        parser.print_help()
        return 1
    conf = cfg.load_config(args.config)
    return args.func(args, conf)


if __name__ == '__main__':
    sys.exit(main())
