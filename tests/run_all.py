#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一测试入口（成员C 主导整体测试）

一次运行三块测试并汇总，生成 Markdown 测试报告：
  1. hadoop   —— 成员A：清洗与五维评分（tests/hadoop，若存在 unittest 用例）
  2. agent    —— 成员B：Agent 接口与调度（tests/agent）
  3. frontend —— 成员C：前端渲染（Node）+ 三层一致性（Python）
  4. consistency —— 成员C：Hadoop→Agent→前端 端到端一致性

用法：
  python tests/run_all.py                # 跑全部
  python tests/run_all.py --only frontend
  python tests/run_all.py --report ../reports/test-report/test-report.md

零依赖：仅标准库 + 可选调用本机 node。
"""

import argparse
import datetime
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def _run_subprocess(cmd, cwd, env=None):
    """跑一条命令，返回 (returncode, 合并输出)。"""
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', env=env,
                           shell=False)
        return p.returncode, (p.stdout or '') + (p.stderr or '')
    except FileNotFoundError as e:
        return 127, '命令不可用: %s' % e


def run_python_unittest(start_dir):
    """在独立子进程中以该目录为工作目录运行 unittest discover。

    子进程方式的原因：各块测试用 `import _paths` 依赖"当前目录即测试目录"
    的约定（成员B设定），且隔离 sys.path，避免跨块模块名冲突。

    返回 (总数, 失败数, 输出)。
    """
    if not os.path.isdir(start_dir):
        return 0, 0, '（目录不存在：%s）' % start_dir
    has_test = any(f.startswith('test_') and f.endswith('.py')
                   for f in os.listdir(start_dir))
    if not has_test:
        return 0, 0, '（无 test_*.py 用例）'
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    code, out = _run_subprocess(
        [sys.executable, '-m', 'unittest', 'discover', '-v'],
        cwd=start_dir, env=env)
    total = bad = 0
    for line in out.splitlines():
        s = line.strip()
        if s.startswith('Ran ') and ' test' in s:
            try:
                total = int(s.split()[1])
            except Exception:
                pass
    # 统计失败/错误条数（-v 下以 "FAIL:" / "ERROR:" 起头）
    bad = sum(1 for line in out.splitlines()
              if line.startswith('FAIL:') or line.startswith('ERROR:'))
    if code != 0 and bad == 0 and total > 0:
        bad = 1
    if total == 0 and code != 0:
        bad = 1
    return total, bad, out


def run_node_frontend():
    """运行前端渲染逻辑测试（Node）。"""
    script = os.path.join(HERE, 'frontend', 'test_render.mjs')
    if not os.path.exists(script):
        return 0, 0, '（无前端 Node 用例）'
    code, out = _run_subprocess(['node', script], cwd=REPO)
    # 前端脚本用退出码表示成败；从输出里取通过/失败数
    passed = failed = 0
    for line in out.splitlines():
        if line.startswith('结果：'):
            try:
                part = line.replace('结果：', '').replace('通过', '').replace('失败', '')
                nums = [int(x) for x in __import__('re').findall(r'\d+', line)]
                if len(nums) >= 2:
                    passed, failed = nums[0], nums[1]
            except Exception:
                pass
    if code != 0 and failed == 0:
        failed = 1  # 非零退出但未解析到，保守记 1 失败
    return passed + failed, failed, out


def main():
    ap = argparse.ArgumentParser(description='统一测试入口（成员C）')
    ap.add_argument('--only', choices=['hadoop', 'agent', 'frontend',
                                       'consistency', 'all'], default='all')
    ap.add_argument('--report', default=None,
                    help='测试报告输出路径（Markdown）')
    args = ap.parse_args()

    targets = [] if args.only == 'all' else [args.only]
    blocks = []  # (名称, 总数, 失败, 输出)

    def want(name):
        return args.only == 'all' or name in targets

    print('=' * 64)
    print(' MovieLens 数据治理系统 · 统一测试（成员C 主导）')
    print(' 时间：%s' % datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    print('=' * 64)

    if want('hadoop'):
        d = os.path.join(HERE, 'hadoop')
        t, b, o = run_python_unittest(d)
        blocks.append(('Hadoop 清洗与评分（成员A）', t, b, o))
        print('\n[Hadoop] %d 用例, %d 失败' % (t, b))

    if want('agent'):
        d = os.path.join(HERE, 'agent')
        t, b, o = run_python_unittest(d)
        blocks.append(('Agent 接口与调度（成员B）', t, b, o))
        print('\n[Agent] %d 用例, %d 失败' % (t, b))

    if want('frontend'):
        t, b, o = run_node_frontend()
        blocks.append(('前端渲染逻辑（成员C · Node）', t, b, o))
        print('\n[Frontend/渲染] %d 用例, %d 失败' % (t, b))

    if want('consistency'):
        d = os.path.join(HERE, 'frontend')
        t, b, o = run_python_unittest(d)
        blocks.append(('三层结果一致性（成员C · Python）', t, b, o))
        print('\n[Consistency] %d 用例, %d 失败' % (t, b))

    # ---- 汇总 ----
    total = sum(b[1] for b in blocks)
    failed = sum(b[2] for b in blocks)

    print('\n' + '=' * 64)
    print(' 汇总：共 %d 用例，失败 %d' % (total, failed))
    for name, t, b, _ in blocks:
        print('   %-40s %3d 用例 / %d 失败' % (name, t, b))
    print('=' * 64)

    if args.report:
        write_report(args.report, blocks)

    return 1 if failed else 0


def write_report(path, blocks):
    total = sum(b[1] for b in blocks)
    failed = sum(b[2] for b in blocks)
    lines = []
    lines.append('# 系统测试报告（成员C）\n')
    lines.append('- 生成时间：%s' % datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    lines.append('- 运行环境：Python %s · Node %s'
                 % (sys.version.split()[0], _node_version()))
    lines.append('- 用例总数：**%d**，失败：**%d**，结论：**%s**\n'
                 % (total, failed, '通过' if failed == 0 else '存在失败'))

    lines.append('## 一、测试范围与结果\n')
    lines.append('| 测试块 | 负责人 | 用例数 | 失败数 | 结果 |')
    lines.append('| --- | --- | ---: | ---: | :--: |')
    owner = {
        'Hadoop 清洗与评分（成员A）': '成员A',
        'Agent 接口与调度（成员B）': '成员B',
        '前端渲染逻辑（成员C · Node）': '成员C',
        '三层结果一致性（成员C · Python）': '成员C',
    }
    for name, t, b, _ in blocks:
        lines.append('| %s | %s | %d | %d | %s |'
                     % (name, owner.get(name, '—'), t, b,
                        'PASS' if b == 0 else 'FAIL'))

    lines.append('\n## 二、测试类别说明\n')
    lines.append('''\
本测试覆盖分工文档"第六.5 系统测试"要求的三个类别：

### 1. 功能测试
- 能否提交任务（POST /api/tasks 正常返回 task_id）；
- Agent 能否正常调用 Hadoop（起测试夹具模拟成员A服务）；
- Hadoop 是否成功返回结果；
- 前端是否正确显示结果（渲染逻辑单测 + 端到端代理采样）。

### 2. 异常测试
- Hadoop 执行失败（在 clean / before / after 各环节注入失败）；
- 数据文件不存在 / Hadoop 服务不可用；
- 请求参数非法（缺 prompt、非法 data_version / rule_version / score_config）；
- Agent 调用失败时前端反代返回可解析错误、不崩溃；
- 任务超时（前端轮询上限）。

### 3. 结果一致性测试（成员C 重点）
验证三层数据一致：
```
Hadoop 实际结果  →  Agent 返回结果  →  前端展示结果
```
- 前端代理出口结果与 Agent 直连接口结果**逐字节一致**；
- Agent 结果的五维分值、统计量、变化值与 Hadoop 层输出**逐字段一致**；
- 任务未完成时**不返回任何数值**（接口规范第 2.2 节）。

## 三、复现方式

```bash
# 全部测试
python tests/run_all.py --report reports/test-report/test-report.md

# 仅前端渲染（Node）
node tests/frontend/test_render.mjs

# 仅三层一致性（Python）
python tests/frontend/test_e2e_consistency.py
```
''')

    lines.append('\n## 四、各测试块原始输出\n')
    for name, t, b, o in blocks:
        lines.append('### %s（%d 用例 / %d 失败）\n' % (name, t, b))
        lines.append('```')
        lines.append((o or '').strip())
        lines.append('```\n')

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print('\n测试报告已写入: %s' % path)


def _node_version():
    try:
        p = subprocess.run(['node', '--version'], capture_output=True,
                           text=True, encoding='utf-8')
        return (p.stdout or '').strip() or '—'
    except Exception:
        return '—'


if __name__ == '__main__':
    sys.exit(main())
