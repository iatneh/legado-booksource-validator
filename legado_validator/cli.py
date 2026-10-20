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


def _load_overrides(specs):
    """把重测结果按 index 归并成 {server: {index: result}}。"""
    over = {}
    for item in (specs or []):
        name, path = item.split('=', 1)
        with open(path, 'r', encoding='utf-8') as fh:
            rows = json.load(fh)
        bucket = over.setdefault(name, {})
        for r in rows:
            if r.get('i') is not None:
                bucket[r['i']] = r
    return over


def _load_drop_keys(path):
    """读取重复书源清单 -> {(书源名, 书源地址): 记录}。

    清单是去重脚本产出的 JSON 数组，每项至少含 bookSourceName /
    bookSourceUrl，可另带 searchEndpoint / keptAs 等说明字段。
    """
    if not path:
        return {}
    with open(path, 'r', encoding='utf-8') as fh:
        data = json.load(fh)
    out = {}
    for rec in data:
        key = (rec.get('bookSourceName'), rec.get('bookSourceUrl'))
        out[key] = rec
    return out


def cmd_merge(args, conf):
    with open(args.src, 'r', encoding='utf-8') as fh:
        sources = json.load(fh)
    results = _load_results(args.result)
    overrides = _load_overrides(getattr(args, 'override', None))
    drops = _load_drop_keys(getattr(args, 'drop_duplicates', None))
    result = merge(sources, results, cn_server=args.cn_server,
                   overseas_server=args.overseas_server,
                   overrides_by_server=overrides, drop_keys=drops)
    paths = write_outputs(result, args.out_dir)
    _log('总书源: %d  保留: %d  剔除: %d  重复剔除: %d  需外网: %d  仅国内: %d  实测可用: %d' % (
        len(sources), len(result['kept']), len(result['removed']),
        len(result.get('dropped') or []), len(result['overseas']),
        len(result.get('cn_only') or []), len(result['verified'])))
    for key in sorted(result['stats']):
        _log('  %-22s %d' % (key, result['stats'][key]))
    for name, path in sorted(paths.items()):
        _log('  输出 %-24s %s' % (name, path))
    report = build_report(sources, result['kept'], result['removed'],
                          list(results.keys()), groups=result.get('groups'),
                          extra=_parse_notes(getattr(args, 'note', None)),
                          duplicates=result.get('dropped'))
    rp = write_report(report, os.path.join(args.out_dir, 'report.md'))
    _log('  输出 %-24s %s' % ('report.md', rp))
    return 0


def _parse_notes(items):
    """把 --note 参数整理成报告里的附加条目。

    支持两种写法：``key=value``（渲染成 "- key：value"）和纯文本
    （渲染成 "- 文本"）。
    """
    out = []
    for it in (items or []):
        it = str(it).strip()
        if not it:
            continue
        if '=' in it:
            k, v = it.split('=', 1)
            out.append('%s：%s' % (k.strip(), v.strip()))
        else:
            out.append(it)
    return out


def cmd_repair(args, conf):
    from .repair import repair_all
    with open(args.src, 'r', encoding='utf-8') as fh:
        sources = json.load(fh)
    with open(args.spec, 'r', encoding='utf-8') as fh:
        specs = json.load(fh)
    only = None
    if args.only:
        only = [int(x) for x in args.only.replace(' ', '').split(',') if x]
    fixed, report = repair_all(
        sources, specs, args.server, args.out, args.report,
        result_path=args.result, timeout=args.timeout, kw0=args.kw,
        keywords=conf.get('keywords'), user_agent=conf.get('user_agent'),
        only=only, progress=_log)
    ok = sum(1 for v in report.values() if v.get('ok'))
    _log('节点 %s 修复成功 %d / 尝试 %d' % (args.server, len(fixed), len(report)))
    _log('输出 %s' % args.out)
    _log('输出 %s' % args.report)
    return 0


def cmd_deeprepair(args, conf):
    """从真实页面反推并修复目录/正文规则。"""
    from .deeprepair import deep_repair_all
    with open(args.src, 'r', encoding='utf-8') as fh:
        sources = json.load(fh)
    with open(args.spec, 'r', encoding='utf-8') as fh:
        specs = json.load(fh)
    only = None
    if args.only:
        only = [int(x) for x in args.only.replace(' ', '').split(',') if x]
    fixed, report = deep_repair_all(
        sources, specs, args.server, args.out, args.report,
        result_path=args.result, timeout=args.timeout, kw0=args.kw,
        keywords=conf.get('keywords'), user_agent=conf.get('user_agent'),
        only=only, progress=_log)
    ok = sum(1 for v in report.values() if v.get('ok'))
    _log('节点 %s 深链修复成功 %d / 尝试 %d' % (args.server, ok, len(report)))
    _log('输出 %s' % args.out)
    _log('输出 %s' % args.report)
    return 0


def cmd_explore(args, conf):
    """补全缺失的发现页规则。"""
    from .explore import supplement_all
    with open(args.src, 'r', encoding='utf-8') as fh:
        sources = json.load(fh)
    only = None
    if args.only:
        only = [int(x) for x in args.only.replace(' ', '').split(',') if x]
    fixed, report = supplement_all(
        sources, timeout=args.timeout, user_agent=conf.get('user_agent'),
        only=only, progress=_log, force=getattr(args, 'force', False))
    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump(fixed, fh, ensure_ascii=False, indent=1)
    with open(args.report, 'w', encoding='utf-8') as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    _log('发现页规则补全 %d 条（尝试 %d 条）' % (len(fixed), len(report)))
    _log('输出 %s' % args.out)
    _log('输出 %s' % args.report)
    return 0


def cmd_patch(args, conf):
    """把修复结果 / 发现页补全结果合并回书源列表。"""
    from .patcher import patch_sources, write_patched
    with open(args.src, 'r', encoding='utf-8') as fh:
        sources = json.load(fh)
    repairs = [p.split('=', 1)[1] for p in (args.repair or [])]
    explores = [p.split('=', 1)[1] for p in (args.explore or [])]
    out, stats = patch_sources(sources, repairs, explores)
    write_patched(out, args.out)
    _log('打补丁完成: 修复规则 %d 条, 发现页规则 %d 条 -> %s' % (
        stats['repair_applied'], stats['explore_applied'], args.out))
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
    sp.add_argument('--override', action='append',
                    help='节点名=修复后重测结果文件，可重复（按下标覆盖）')
    sp.add_argument('--out-dir', required=True)
    sp.add_argument('--drop-duplicates',
                    help='重复书源清单 JSON（去重脚本产出），这些源不进入产出')
    sp.add_argument('--cn-server')
    sp.add_argument('--overseas-server')
    sp.add_argument('--note', action='append', help='报告附加说明，形如 key=value')
    sp.set_defaults(func=cmd_merge)

    sp = sub.add_parser('deep-repair', help='从真实页面反推并修复目录/正文规则')
    sp.add_argument('--src', required=True)
    sp.add_argument('--spec', required=True)
    sp.add_argument('--result', help='本节点上一次的校验结果，用来筛出深链断裂的书源')
    sp.add_argument('--out', required=True, help='修复后的书源')
    sp.add_argument('--report', required=True, help='修复诊断报告')
    sp.add_argument('--server', required=True)
    sp.add_argument('--timeout', type=int, default=25)
    sp.add_argument('--kw', default='修真')
    sp.add_argument('--only', help='只处理指定下标，逗号分隔')
    sp.set_defaults(func=cmd_deeprepair)

    sp = sub.add_parser('explore', help='补全缺失的发现页规则（ruleExplore）')
    sp.add_argument('--src', required=True)
    sp.add_argument('--out', required=True, help='补全后的书源')
    sp.add_argument('--report', required=True, help='补全诊断报告')
    sp.add_argument('--timeout', type=int, default=25)
    sp.add_argument('--only', help='只处理指定下标，逗号分隔')
    sp.add_argument('--force', action='store_true',
                    help='连已经有 ruleExplore.bookList 的书源也重做')
    sp.set_defaults(func=cmd_explore)

    sp = sub.add_parser('patch', help='把修复/发现页结果合并回书源列表')
    sp.add_argument('--src', required=True)
    sp.add_argument('--repair', action='append', help='修复结果文件，可重复')
    sp.add_argument('--explore', action='append', help='发现页补全结果文件，可重复')
    sp.add_argument('--out', required=True)
    sp.set_defaults(func=cmd_patch)

    sp = sub.add_parser('repair', help='从真实结果页反推并修复书源规则')
    sp.add_argument('--src', required=True)
    sp.add_argument('--spec', required=True)
    sp.add_argument('--result', help='本节点上一次的校验结果，用来筛出待修复书源')
    sp.add_argument('--out', required=True, help='修复后的书源')
    sp.add_argument('--report', required=True, help='修复诊断报告')
    sp.add_argument('--server', required=True)
    sp.add_argument('--timeout', type=int, default=25)
    sp.add_argument('--kw', default='修真')
    sp.add_argument('--only', help='只处理指定下标，逗号分隔')
    sp.set_defaults(func=cmd_repair)

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
