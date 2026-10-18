# 迭代二 GitHub 协作与提交计划

## 一、协作原则

沿用仓库现有结构及迭代一协作规则：一个共享仓库，`main` 保存可运行的稳定版本，三人各自使用功能分支开发，通过 Pull Request 审核和合并。合作者可以并行开发自己的模块，但不应未经审核直接把未验证代码并入 `main`。

## 二、建议分支

| 成员/用途 | 分支名称 | 主要修改范围 |
|---|---|---|
| A：分类和数据准备 | `feature/iter2-classification` | 数据版本对接、特征准备、分类工具、分类测试 |
| B：聚类和 Agent 集成 | `feature/iter2-clustering-agent` | 聚类工具、画像、Agent 路由、任务状态及结果封装 |
| C：降维和前端 | `feature/iter2-dimensionality-frontend` | 降维工具、二维可视化、前端页面、前端测试 |
| 文档/接口冻结（可由 B 汇总） | `docs/iteration2-contracts` | 只在需要时短期使用，合并后删除或停止使用 |

若某一功能需要分多次提交，可在负责人的功能分支内连续提交；不要为了每个小文件都额外建分支。需要修改公共接口时，优先先提交文档 PR，待 A/B/C 确认再同步代码。

## 三、开发前必须完成

- [ ] 阅读迭代二需求原文和本套文档
- [ ] 核对课程 PPT，为分类/聚类/降维各登记两种算法及 PPT 页码
- [ ] 确认输入清洗数据版本和既有 `T1/T2`
- [ ] 确认接口扩展规范与现有 `docs/接口规范文档.md` 的兼容关系
- [ ] 为任务建立 GitHub Issues，明确负责人、完成标准和依赖
- [ ] 确认模型/坐标/报告产物的保存和交接方式

## 四、建议 Issues

### 成员A

- `[Iteration 2][Data] 确认清洗数据版本与 T1/T2`
- `[Iteration 2][Classification] 构造无泄漏特征和高分标签`
- `[Iteration 2][Classification] 实现分类算法一`
- `[Iteration 2][Classification] 实现分类算法二`
- `[Iteration 2][Classification] 评估、保存模型和版本元数据`

### 成员B

- `[Iteration 2][Clustering] 定义训练期用户画像`
- `[Iteration 2][Clustering] 实现聚类算法一`
- `[Iteration 2][Clustering] 实现聚类算法二`
- `[Iteration 2][Agent] 注册六种分析工具并路由请求`
- `[Iteration 2][Agent] 统一任务状态、错误及结果接口`

### 成员C

- `[Iteration 2][Reduction] 实现降维算法一`
- `[Iteration 2][Reduction] 实现降维算法二`
- `[Iteration 2][Reduction] 增加降维前后聚类对照和二维图`
- `[Iteration 2][Frontend] 展示分类/聚类/降维结果`
- `[Iteration 2][Test] 完成端到端测试和验收报告`

### 全员共同

- `[Iteration 2][Contract] 冻结接口字段和算法选择记录`
- `[Iteration 2][Integration] 真实数据端到端联调`
- `[Iteration 2][Release] 归档模型、画像、群体、坐标和报告`

## 五、Commit 规范

格式：`类型: 简短描述`。建议类型：`feat`、`fix`、`docs`、`test`、`refactor`、`chore`。

示例：
- `feat: add classification algorithm tool`
- `feat: add user clustering summary`
- `feat: add dimensionality reduction visualization`
- `fix: reject prediction features from future events`
- `docs: define iteration two analysis API`
- `test: cover insufficient user history`

一次提交聚焦于一个可以理解和回退的改动；不要使用 `update`、`final`、`test` 等无法说明具体内容的提交信息。

## 六、Pull Request 要求

每个 PR 应填写：

- 本次修改内容与对应 Issue；
- 影响的任务类型/目录；
- 所选算法和课程 PPT 页码（算法实现 PR）；
- 数据、特征、画像或模型版本；
- 运行过的测试命令及实际结果；
- 生成的报告/图表/产物路径；
- 接口是否变更；若变更，说明兼容方案；
- 已知限制或尚未解决的问题。

合并前检查：代码可读、接口文档已同步、测试结果真实、无原始大数据/凭据误提交、异常路径有处理。建议至少一名其他成员审核；涉及公共接口时需 A/B/C 三方确认字段影响。

## 七、日常同步与冲突处理

开始工作前：

```bash
git checkout main
git pull origin main
git checkout feature/your-branch
git merge main
```

开发、测试后：

```bash
git status
git diff
git add <明确的文件或目录>
git commit -m "feat: describe the change"
git push -u origin feature/your-branch
```

随后在 GitHub 创建 PR，目标分支选择 `main`。在 `main` 开启分支保护，要求 PR 合并并至少一人批准；如果仓库设置允许管理员绕过规则，应由团队确认是否关闭绕过权限。

出现冲突时，冲突分支负责人先与涉及文件的负责人协商，再合并最新 `main`、人工解决冲突、重新运行相关测试并推送。不要通过强制推送覆盖他人已共享的提交。

## 八、建议合并顺序

1. 先合并接口规范、算法选择记录和数据切分约定。
2. A/B/C 各自提交可独立运行的算法工具与测试。
3. B 完成六种工具的注册及任务路由。
4. C 完成三类结果展示和真实接口联调。
5. 全员完成端到端验收后更新根目录唯一 `README.md`，整理 `reports/` 并合并最终 PR。

## 九、发布前仓库检查

- [ ] `main` 能按文档运行；
- [ ] PR/Commit 能清楚追溯各成员工作；
- [ ] 文档所写接口与代码一致；
- [ ] 产物版本与数据版本、`T1/T2` 对齐；
- [ ] 六种算法工具均有实际运行证据；
- [ ] 原始 `ml-1m.zip` 没有进入 Git；
- [ ] `reports/` 的质量报告和测试报告已更新；
- [ ] 迭代三接手人能定位并读取模型/画像/群体/坐标产物。
