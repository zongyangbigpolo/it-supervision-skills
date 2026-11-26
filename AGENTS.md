# AGENTS.md — 信息监理 skill 套件使用说明（供 AI Agent 读取）

本仓库是一套面向**中文信息技术服务监理（信息系统工程监理）人员**的 Agent Skills，遵循通用 `SKILL.md`（YAML frontmatter + Markdown）格式，可被 Claude Code / Claude Desktop、WorkBuddy、CodeBuddy、GitHub Copilot、Codex 等支持 skills 的 Agent 加载。

## 你（Agent）应当如何使用

1. 用户提出任何信息监理文书需求时，先读取 `skills/it-supervision-core/SKILL.md`，完成其中“第 0 步：建立/读取项目档案”。
2. 按 core 中的路由表进入对应子 skill，严格按子 skill 的工作流执行。
3. 始终使用简体中文输出；文书风格为中文公文/工程文书风格。
4. **绝不编造事实**（日期、数量、金额、序列号、人员、测评分数、标准条款号）；缺失信息标 `【待填】` 并在最后列出待补充清单。
5. 先给 Markdown 草稿，用户确认后再用 `skills/it-supervision-core/scripts/md_to_docx.py` 渲染为 DOCX 正式件。

## 目录

```
skills/
├── it-supervision-core/      # 总控：项目档案、编号、签章栏、DOCX 渲染、校验
├── supervision-plan/         # 监理规划 / 监理实施细则
├── supervision-log/          # 监理日志 / 监理周报
├── supervision-notice/       # 监理通知单 / 回复单 / 暂停令 / 复工令 / 联系单
├── stage-acceptance/         # 阶段验收 / 初验 / 终验
├── mlps-check/               # 等保测评监理检查
├── hardware-arrival-check/   # 硬件到货验收 + 清单自动比对
└── site-photos/              # 现场照片按文件名/水印/日期自动匹配并插入文书
```

## 开发约定（修改本仓库时）

- 子 skill 通过相对路径 `../it-supervision-core/` 引用公共脚本与规范，新增 skill 也须遵循。
- 新增文书类型时，同步更新：`common.py` 的 `DOC_TYPES`、`references/文书规范与编号.md`、`references/签章栏规范.md`、`validate_doc.py` 的 `REQUIRED`（如需）。
- 模板中的正式文书必须含 `<!-- signature:... -->` 签章栏标记。
- 运行测试：`python3 -m unittest discover -s tests -v`。
