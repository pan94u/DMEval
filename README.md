# 决策模型评测工作台

打开 **http://localhost:8787**，维护样本、创建单样本或批量测试任务，并比较模型的判断。只有明确运行任务时才调用模型。

## 使用流程

1. **维护样本**：填写要测试的内容、问题名称、判断标准与参考答案。支持是／否、选择答案、等级评分；已有结构化内容可以通过中文表单编辑。
2. **创建任务**：选择样本、模型、重复次数。可以只保存，或立即运行；评分题可以指定允许误差。
3. **查看结果**：用答案含义对比预期和实际判断，查看未成功或不符合预期的测试；详情末尾可展开原始输入输出。
4. **预览判断阈值**：仅对是／否问题调整“何时判断为是”。滑动仅预览，点击“保存到此任务”后结果页才改变，刷新后保留。

样本按业务内容展示，内部编号和模型字段不作为正文。原始内容仅在末尾折叠区查看。系统不为决策模型补写它未提供的推理解释。原始 JSONL／JSON 导入、导出供批量维护使用，结果报告默认导出为人类可读 CSV；CSV 文本做公式注入防护。

任务创建后保存当时的样本副本。后续编辑样本库不改变旧任务。任务可取消、复制、移出列表；复制会继承明确保存的判断规则。不存在早期记录入口或保留旧记录的兼容分支。

## 判断规则

是／否问题的默认阈值为 50%。模型给“是”的分数 **大于等于** 阈值时判为是；模型分数不保证等于真实世界的发生概率。不同任务、模型、判断规则分别保存阈值。判断规则身份包括问题编号、完整标准与候选描述，不能混用不同问题。

选择题按最高概率候选项判断；评分题按等级概率的加权期望评分，使用独立的允许误差（默认 0.5 分），不会套用二元阈值。

阈值分析复用保存的分数，不重新调用模型。同一样本重复请求先取平均分数再分析，并报告独立样本数；结果表保留每次测试。单类别数据只展示预览，不将其包装为完整模型评估。选阈值需要权衡误报与漏报，并使用独立样本验证；当前没有交叉验证自动调参。完整接口审查与依据见 [THRESHOLD_REVIEW.md](THRESHOLD_REVIEW.md)。

## 运行与配置

Python 3.11+，仅标准库。当前部署在 WSL Ubuntu：

```bash
cd /home/szq43/code/decision-model-eval
systemctl --user status decision-dashboard.service
systemctl --user status decision-task-worker.service
```

- `decision-dashboard.service`：中文界面与本机 API，监听 127.0.0.1:8787。
- `decision-task-worker.service`：执行明确加入队列的任务，空闲时不调用模型。关闭网页不停止任务；主机或 WSL 停止时暂停。

若 Windows / WSL 镜像网络的 localhost 转发异常，可在 PowerShell 中运行项目内的 `Start-Workbench.ps1`。它在 Windows 的 127.0.0.1:8787 启动隐藏的本机入口，通过固定的 WSL 标准输入桥接调用同一应用层；SQLite、凭证与任务工作进程仍留在 Linux，不跨系统直接打开数据库。Linux HTTP 入口会先停止，防止同一端口冲突。此方案不修改路由、防火墙或 WSL 网络配置。当前机器使用该 Windows 入口；关闭终端后继续运行，Windows 重启后可重新执行启动脚本。

部署服务文件包含本机路径，迁移后需修改 WorkingDirectory、EnvironmentFile 和 ExecStart。

`.env` 保存账户与 API 令牌，权限 600，不能提交到 Git。任务服务通过 EnvironmentFile 加载；浏览器不会收到凭证。写入操作校验本机 Host、Origin 与会话令牌。

## 数据

`runs/evaluations.sqlite3` 保存：

- `samples`：样本内容、业务分组、版本及移除标记。
- `tasks`：任务配置与不可变样本副本。
- `runs` / `results`：任务执行与原始响应。
- `task_policies`：按任务、模型、问题保存的已应用阈值。

`runs/tasks/` 保存任务输入及执行日志。参考答案、标注说明、界面展示名称等不发送给模型。数据可能包含业务内容，应按业务数据保管整个 runs 目录。

`data/smoke.jsonl` 是首次启动的四个示例；`data/challenge-v1.jsonl` 是 32 个 AI 编写的合成对照样本，未经独立人工审核，不能代表真实业务分布或公开基准。

## 验证与脚本

```bash
python3 -m unittest -v
python3 verify_dashboard.py
python3 verify_tasks.py
```

默认验证使用离线均匀概率基线。`verify_tasks.py --live` 会产生真实模型请求。浏览器验证脚本包含本工作区运行时路径，迁移后需调整。

保留显式单次运行 CLI，用于任务执行和批量脚本：

```bash
python3 eval.py run --provider mock --dataset data/smoke.jsonl
python3 eval.py run --provider cloudflare --models clef,clef-flash --fresh
python3 eval.py run --provider systemone --endpoint https://YOUR-HOST/v1/systemone --models YOUR-MODEL
```

CLI 须通过环境变量提供凭证，不自动加载 `.env`。相同输入和代码版本自动续跑，`--fresh` 建立新批次。
