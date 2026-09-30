/* MovieLens 数据治理 Agent —— 前端接口层（成员C）
 *
 * 职责：只调用成员B提供的 Agent API（接口规范第 18 节）。
 *   前端不直接访问 Hadoop 内部实现（接口规范第 2.1 节）。
 *
 * 契约依据：docs/接口规范文档.md
 *   第 4 节   POST /api/tasks                 创建任务
 *   第 6 节   GET  /api/tasks/{task_id}       查询状态
 *   第 13 节  GET  /api/tasks/{task_id}/result 最终评估结果
 *   第 6.2 节 POST /api/tasks/{task_id}/ask   结果追问
 *   第 15 节  错误响应：业务失败返回 HTTP 200 + {status:"FAILED", error:{...}}
 *
 * 铁律（接口规范第 2.2 节）：页面上的任何分数、数量都必须来自
 *   上述接口的返回值。本文件不含任何硬编码的评分或统计数值。
 */

const AgentApi = (function () {
  'use strict';

  // Agent 服务地址：同源部署时留空即可；也可由 ?api=http://host:port 覆盖。
  const params = new URLSearchParams(location.search);
  const BASE = (params.get('api') || '').replace(/\/$/, '');

  function url(path) {
    return BASE + path;
  }

  async function request(method, path, body) {
    const opt = { method, headers: {} };
    if (body !== undefined) {
      opt.headers['Content-Type'] = 'application/json';
      opt.body = JSON.stringify(body);
    }
    let res;
    try {
      res = await fetch(url(path), opt);
    } catch (e) {
      // 网络层失败：服务未启动 / 跨域 / 断网
      throw { code: 'NETWORK_ERROR', message: '无法连接 Agent 服务：' + e.message,
              stage: null };
    }
    let data;
    try {
      data = await res.json();
    } catch (e) {
      throw { code: 'BAD_RESPONSE', message: 'Agent 返回的不是合法 JSON（HTTP ' + res.status + '）',
              stage: null };
    }
    // 业务失败：HTTP 200 + status=FAILED + error（接口规范第 15 节）
    if (data && data.status === 'FAILED' && data.error) {
      throw data.error;
    }
    // 协议级错误：4xx/5xx 且无 error 对象
    if (res.status >= 400) {
      throw { code: 'HTTP_' + res.status, message: '请求失败 HTTP ' + res.status,
              stage: null };
    }
    return data;
  }

  return {
    baseUrl: BASE,

    // 健康检查（成员B的辅助接口，前端用于判断服务是否在线）
    health() {
      return request('GET', '/health');
    },

    // 创建任务：用户自然语言需求（接口规范第 4 节）
    createTask(payload) {
      return request('POST', '/api/tasks', payload);
    },

    // 查询任务状态（接口规范第 6 节）
    getStatus(taskId) {
      return request('GET', '/api/tasks/' + encodeURIComponent(taskId));
    },

    // 查询最终评估结果（接口规范第 13 节）
    getResult(taskId) {
      return request('GET', '/api/tasks/' + encodeURIComponent(taskId) + '/result');
    },

    // 结果追问（接口规范第 6.2 节）
    ask(taskId, question) {
      return request('POST', '/api/tasks/' + encodeURIComponent(taskId) + '/ask',
                     { question });
    },

    // 辅助：任务列表
    listTasks() {
      return request('GET', '/api/tasks');
    }
  };
})();
