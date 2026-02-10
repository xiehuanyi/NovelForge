# Gemini 3 Hackathon Demo · Novel Agents

这是一个基于多智能体写作系统的 demo：
- Create：群聊式创作，多个角色协作。
- Preview：书架式预览每章正文。
- Settings：模型与字数配置。

## 运行方式

```bash
cd gemini-hackathon
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

浏览器打开：`http://localhost:8000`

## 关键说明

- Agent 与 Agent 的协作是单轮调用（pipeline），人类用户负责风格与文笔判断。
- Checker 只检查格式与完整性。
- 输出文件在 `gemini-hackathon/output/<project_slug>/`。

## 模型配置

默认读取 `gemini-hackathon/models_config.json`（Gemini 3 Flash/Pro 配置）。
可以在 `Settings` 中给每个角色指定模型 ID。

示例环境变量：

```bash
export GEMINI_API_KEY=...
```

或者你可以在谷歌AI Studio上面尝试使用这个项目。https://ai.studio/apps/drive/1Klc1mW5IMlrUUYneSHshe0bX6AuEJ6n1?fullscreenApplet=true