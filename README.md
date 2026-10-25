# 决策模型评测工作台

打开 **http://localhost:8787**，使用中文界面维护样本、创建单样本或批量测试任务，并比较模型结果。

**没有定时评测。只有显式运行任务时才调用模型。** 之前的每小时评测服务已经停用，旧结果保留在“查看早期评测记录”。

## 页面操作

### 样本库

- 新增、编辑、复制、移除样本；支持搜索、分组与类型筛选。
- 每个样本包含输入内容、判断规则和标准答案；可含多个问题。
- 三种问题：是 / 否（noul）、多选一（choice）、等级评分（score）。
- 点击单行的“单样本测试”，或勾选多个样本后“创建测试任务”。
- 导入 JSONL / JSON 数组；导出选中的样本，未选择时导出筛选后的列表。
- 导入编号重复时整批拒绝，避免意外覆盖。移除为软删除。

### 测试任务

- 创建任务时指定名称、样本、模型和重复次数，界面展示预计 API 请求数。
- “仅创建任务”保存待运行任务；“创建并运行”加入执行队列。
- 队列按创建时间串行执行，可以离开页面，结果会持续保存。
- 排队或运行中的任务可取消；已执行的任务可以复制为新任务再次运行。
- 创建任务即保存样本副本和版本。样本库后续编辑或移除不改变旧任务。

### 任务详情

- **测试结果**：请求进度、分类准确率、评分误差、失败数、逐样本逐问题结果、完整概率与原始响应。支持模型筛选、错题筛选和导出。
- **决策阈值**：仅对是 / 否问题分析；P(是) ≥ 阈值时判断为是。按模型与完全相同的判断规则分别调整阈值，查看精确率、召回率、F1、TP / FP / FN / TN、概率分布与阈值曲线。
- **样本与配置**：任务创建时的原始样本、标准答案、模型和数据版本。

调整阈值只复用保存的概率，**不会再次调用模型**。当前阈值设置只在当前页面会话中用于分析和导出，不改写原始响应。重新打开页面默认 0.50。探索指标不等于独立验证成绩；确定阈值后应在未参与调整的测试集上验证。当前不自动选择“最佳 F1”、做交叉验证或拟合校准模型。

参考：[Hamel — How To Use Decision Models for Evals](https://hamel.dev/blog/posts/decision-model-evals/#understanding-decision-thresholds)。

## 当前部署

Python 3.11+，标准库，无需安装应用依赖。运行于 WSL Ubuntu，两个用户级 systemd 服务：

```bash
cd /home/szq43/code/decision-model-eval
systemctl --user status decision-dashboard.service
systemctl --user status decision-task-worker.service
```

- `decision-dashboard.service`：本机中文界面及 API，监听 127.0.0.1:8787。
- `decision-task-worker.service`：等待明确创建的排队任务，空闲时不调用模型。服务重启后恢复未完成任务。
- 旧的 `decision-eval.service` 每小时服务已禁用，旧手动服务不再由界面调用。

关闭网页和终端后仍工作；WSL 实例停止或 Windows 关机时暂停。用户服务已经启用随 WSL 用户服务管理器启动。

安装或迁移到相同目录：

```bash
mkdir -p ~/.config/systemd/user
install -m 644 deploy/decision-dashboard.service deploy/decision-task-worker.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now decision-dashboard.service decision-task-worker.service
```

迁移路径时需修改 service 文件中的 WorkingDirectory、EnvironmentFile 和 ExecStart。

## 配置和数据

`.env` 保存 `CLOUDFLARE_ACCOUNT_ID` 和 `CLOUDFLARE_API_TOKEN`，权限为 600，由任务执行服务加载。前端不会收到 API 凭证。控制操作校验本机 Host、Origin 和会话令牌；浏览器界面不向局域网开放。

令牌需有对应账户的 Workers AI 推理权限。接口为 `POST /client/v4/accounts/{account}/ai/run/@cf/cloudflare/{model}`；`/tokens/verify` 仅验证令牌，不能代替推理测试。

数据均在 `runs/evaluations.sqlite3`：

- `samples`：当前样本、分组、版本与软删除标记。
- `tasks`：任务状态、配置与样本副本。
- `runs` / `results`：执行记录、原始模型响应、逐题指标。
- `runs/tasks/`：任务样本副本 JSONL 和执行日志。

首次启动从 `data/smoke.jsonl` 导入四个已有示例，后续由样本库维护。示例数据只适合验证流程，不能代表模型整体能力。原始输入与模型响应可能含业务数据，请按业务数据保管整个 runs 目录。

标准答案永远只在本地使用，不发给模型。请求串行执行，每次请求后提交 SQLite；429、部分 5xx 和网络超时有重试与退避。失败请求单独统计，质量指标不包含失败项。

二元分析 Brier 使用 `(P(是)-标签)^2`，范围 0–1。旧 CLI 汇总 Brier 是每类别平方误差之和，二元时范围 0–2，不能与页面二元 Brier 混用。评分采用概率加权期望和绝对误差，误差大于 0.5 时显示在错题筛选中。重复次数的观测会逐次统计，界面同时提示独立样本数。

## 验证

```bash
python3 -m unittest -v
python3 verify_dashboard.py
python3 verify_tasks.py
```

- 单元测试覆盖指标、重试、凭证异常、恢复、样本版本冲突、任务副本、导入原子性和任务状态。
- `verify_dashboard.py` 检查本机 API 和控制令牌，不调用模型。
- `verify_tasks.py` 默认创建离线验证任务并在结束后从列表移除。
- `verify_tasks.py --live` 会发起 10 次真实 Cloudflare 请求，保留单样本和批量示例任务。
- `verify_browser.cjs` 为本工作区 Playwright / Edge 检查，包含环境专用路径；验证表单、单样本 / 批量选择、队列和阈值边界、移动布局。生成的截图位于 runs。

## CLI 扩展

仍可用 `eval.py run` 做脚本化评测。配置环境变量后支持 Cloudflare，也支持 SystemOne 兼容的 Jev / 本地服务：

```bash
python3 eval.py run --provider mock --dataset data/smoke.jsonl
python3 eval.py run --provider cloudflare --models clef,clef-flash --fresh
python3 eval.py run --provider systemone --endpoint https://YOUR-HOST/v1/systemone --models YOUR-MODEL
```

CLI 默认不读取 `.env`，须通过 shell 导出。相同输入与代码版本生成相同 run ID，已完成项不会再次调用；`--fresh` 创建新批次。旧 `watch` 命令仅保留兼容性，当前界面与服务均不使用。

模型官方资料：[Cloudflare 文档](https://developers.cloudflare.com/workers-ai/models/clef/)、[Clef 模型卡](https://huggingface.co/Cloudflare/clef)。
