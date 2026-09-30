# -*- coding: utf-8 -*-
"""
演示前冒烟脚本（成员C）

一键起三件套并跑一次完整任务，用于演示前自检 / 截图取材：
    前端(8000)  →  Agent(8090)  →  Hadoop(8080)

默认使用"假 Hadoop"夹具（无需真实数据即可演练全链路 UI）；
带 --real-hadoop <url> 时改连成员A的真实服务。

用法：
  # 演练模式（无真实数据，验证 UI 全链路）
  python tests/frontend/smoke_demo.py

  # 真实模式（先自行启动成员A的 Hadoop 服务）
  python tests/frontend/smoke_demo.py --real-hadoop http://127.0.0.1:8080
"""

import argparse
import json
import os
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
for p in (os.path.join(_REPO, 'agent', 'src'),
          os.path.join(_REPO, 'agent', 'tools'),
          os.path.join(_REPO, 'tests', 'agent'),
          os.path.join(_REPO, 'frontend', 'src')):
    if p not in sys.path:
        sys.path.insert(0, p)

import api                      # noqa: E402
import serve as frontend_serve  # noqa: E402
import hadoop_tool              # noqa: E402
from scheduler import PipelineScheduler  # noqa: E402
from store import TaskStore              # noqa: E402
from hadoop_tool import HadoopTool       # noqa: E402


def _post(url, body):
    data = json.dumps(body, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST',
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode('utf-8'))


def _get(url):
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.loads(r.read().decode('utf-8'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--real-hadoop', default=None,
                    help='连真实成员A服务；缺省用测试夹具')
    ap.add_argument('--front-port', type=int, default=8000)
    ap.add_argument('--agent-port', type=int, default=8090)
    args = ap.parse_args()

    dirs = [tempfile.TemporaryDirectory() for _ in range(3)]
    state_dir, tasks_dir, results_dir = (d.name for d in dirs)
    hadoop_tool.STATE_DIR = state_dir

    fake = None
    if args.real_hadoop:
        hadoop_url = args.real_hadoop
    else:
        from fake_hadoop import FakeHadoopServer
        fake = FakeHadoopServer(state_dir)
        hadoop_url = fake.base_url

    store = TaskStore(tasks_dir)
    tool = HadoopTool(base_url=hadoop_url, timeout=15)
    sched = PipelineScheduler(store, tool, results_dir=results_dir)
    sched.start()
    agent_httpd = api.make_server(store, tool, sched, '127.0.0.1',
                                  args.agent_port)
    threading.Thread(target=agent_httpd.serve_forever, daemon=True).start()

    frontend_serve.G['agent_url'] = 'http://127.0.0.1:%d' % args.agent_port
    front_httpd = ThreadingHTTPServer(('127.0.0.1', args.front_port),
                                      frontend_serve.Handler)
    threading.Thread(target=front_httpd.serve_forever, daemon=True).start()

    print('=' * 64)
    print(' 演示环境已启动')
    print('   打开浏览器访问 : http://127.0.0.1:%d' % args.front_port)
    print('   Hadoop 来源    : %s%s' % (hadoop_url,
          '' if args.real_hadoop else '（测试夹具，非真实数据）'))
    print('-' * 64)

    try:
        # 自检：抓页面
        with urllib.request.urlopen('http://127.0.0.1:%d/' % args.front_port,
                                    timeout=10) as r:
            assert r.status == 200
        print(' [1/3] 前端页面可访问 ................ OK')

        # 自检：提交一次任务并等待完成
        created = _post('http://127.0.0.1:%d/api/tasks' % args.agent_port,
                        {'prompt': '请使用默认规则清洗 MovieLens 1M，'
                                   '评估清洗前后的五个数据质量维度。',
                         'data_version': 'movielens-1m-v2'})
        tid = created['task_id']
        print(' [2/3] 任务已创建 %s ............ OK' % tid)
        deadline = time.time() + 30
        while time.time() < deadline:
            st = _get('http://127.0.0.1:%d/api/tasks/%s' % (args.front_port, tid))
            if st['status'] in ('SUCCESS', 'FAILED'):
                break
            time.sleep(0.2)
        print(' [3/3] 任务到达终态：%s ......... OK' % st['status'])

        if st['status'] == 'SUCCESS':
            res = _get('http://127.0.0.1:%d/api/tasks/%s/result'
                       % (args.front_port, tid))
            print('-' * 64)
            print(' 五维评分（前 → 后）：')
            for d in ('accurate', 'complete', 'unique', 'up_to_date', 'consistent'):
                print('   %-12s %s → %s' % (d, res['before_score'][d],
                                            res['after_score'][d]))
            s = res['statistics']
            print(' 数据量：%s → %s（修复 %s / 去重 %s / 隔离 %s）'
                  % (s['before_count'], s['after_count'], s['fixed_count'],
                     s['deduplicated_count'], s['isolated_count']))
        print('=' * 64)
        print(' 浏览器中继续操作；按 Ctrl+C 结束演示环境。')
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print('\n 正在停止 ...')
    finally:
        front_httpd.shutdown(); front_httpd.server_close()
        agent_httpd.shutdown(); agent_httpd.server_close()
        sched.stop()
        if fake:
            fake.stop()
        for d in dirs:
            d.cleanup()
    return 0


if __name__ == '__main__':
    sys.exit(main())
