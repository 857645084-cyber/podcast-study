# 第三方组件

本仓库脚本和文档使用 MIT；该许可不授予播客内容的版权。

依赖通过安装获取，不随本仓库分发：
- [Casts Down](https://github.com/host452b/casts_down)：MIT；只调用其下载命令，未复制源码。
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)：MIT；语音识别。
- [PyAV](https://github.com/PyAV-Org/PyAV)：BSD-3-Clause；音频解码。锁定 16.1.0，避免已遇到的接口不兼容。
- [FFmpeg](https://ffmpeg.org/legal.html)：按所用构建可能为 LGPL 或 GPL；用户单独安装，仓库不打包二进制。
- Whisper 模型单独下载，使用前参见相应模型仓库许可（默认 Systran/faster-whisper-small）。

可选文章流程参考并调用 [orange2ai/podcast-to-article](https://github.com/orange2ai/podcast-to-article)（MIT），作者 orange2ai。该 Skill 未复制进本仓库，不是运行转写或学习笔记的必要条件；若未来合并其文件，需一并保留其许可证及版权声明。
