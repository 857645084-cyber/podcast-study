# 播客学习整理 / Podcast Study

一个面向个人学习的 Agent Skill：公开小宇宙单集或本地音频 → 本地文字稿 → 有时间戳依据的学习笔记。可继续追问案例、讨论观点，或按需生成文章。

音频识别在本地运行；学习笔记由你正在使用的 AI Agent 生成。在线 Agent 阅读文字时，文字会提交给相应服务，所以整个学习流程不等于完全离线。无需额外配置转写 API Key。

## 安装

目前在 Windows / Python 3.12 上验证。先安装 Python 3.12 和 FFmpeg，确保 `python`、`ffmpeg` 可运行。下载本仓库并进入目录，在 PowerShell 执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts/podcast.py doctor
```

将仓库的 `SKILL.md`、`scripts`、`references`、`agents`、`README.md`、`requirements.txt`、`LICENSE` 和 `THIRD_PARTY.md` 一起放入 Agent 的个人 Skills 目录，文件夹名 `podcast-study`。Codex 常见位置为用户目录下 `.codex/skills/podcast-study`。虚拟环境留在项目目录，不复制；让 Agent 使用其 Python 完整路径执行脚本。

## 使用

对 Agent 说：“用 podcast-study 整理这期播客的学习笔记”，附单集链接或本地音频。已有文字稿也能直接整理，不必重跑识别。

也可以手动执行：

```powershell
# 本地文件，先试转一分钟；试转使用独立输出目录
.\.venv\Scripts\python.exe scripts/podcast.py run "C:\Audio\episode.m4a" --out "output\trial" --preview 60

# 同一音频，正式处理
.\.venv\Scripts\python.exe scripts/podcast.py run "C:\Audio\episode.m4a" --out "output\episode"

# 公开单集，把占位符换成自己的单集 ID
.\.venv\Scripts\python.exe scripts/podcast.py run "https://www.xiaoyuzhoufm.com/episode/EPISODE_ID" --out "output\episode-link"
```

默认 small 中文模型、CPU int8。首次需联网下载约 484 MB 模型，并下载语音活动检测等依赖资源。可用 `--model "本地模型目录"` 复用已下载模型；`--language auto` 自动识别语言；`--threads 4` 限制 CPU 线程。中断后用原命令恢复，不要改输出目录或设置。改变音频、模型、语言或分段参数请用新目录。

## 产物

每期目录包含原始 TXT、带时间戳 SRT、逐段 JSON 检查点、质量疑点、处理记录和日志。脚本不会自动写学习笔记；Agent 通读文本后才生成 `学习笔记.md`，明确区分主讲内容、AI 解读、用户想法。文章是可选产物，可配合 orange2ai 的 podcast-to-article Skill。

## 已知限制

- 三分钟一段，段边界可能影响半句话，需回听。没有说话人自动识别。
- 中文人名、英文术语、数字和重叠说话可能识别错误；自动质量检查无法发现全部问题。
- 首段速度不能保证整期速度，笔记本上长节目可能处理很久。保持电脑唤醒。
- 小宇宙公开页面依赖第三方下载器，平台变化可能导致失败；不处理付费或登录绕过。
- 暂不做订阅、批量处理、自动发布。不要把个人音频或笔记提交进开源仓库。
- 下载失败最多自动尝试两次；保留 run.log。强制终止可能留下 `.run.lock`，确认进程已退出后才删除它再恢复。

## 验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

测试使用临时生成音频及模拟识别器验证中断、缓存、损坏段恢复、输入变化保护和时间轴；真实识别另用短中文音频验收。详见 `VALIDATION.md`。

本项目 MIT 开源。依赖和可选 Skill 的许可、来源见 [THIRD_PARTY.md](THIRD_PARTY.md)。
