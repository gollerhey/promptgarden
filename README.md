# promptgarden

**管理一组提示词变体并比较它们的表现。**

`promptgarden` —— 维护提示词变体集合，在同一批输入上跑出对照结果并排出优劣。

- 零依赖，Python 3.10+ 标准库即可运行
- 单文件，`promptgarden.py` 拷走就能用
- 不联网、不写文件

<!-- ipos:install -->
## 安装

零依赖，Python 3.10+ 即可：

```bash
pip install gollerhey-promptgarden
```

装完直接用命令名调用：

```bash
promptgarden --help
```

也可以不用安装，直接把 `promptgarden.py` 拷走用——它只依赖标准库。

## 为什么需要它

提示词测试框架多要接后端；promptgarden 用固定输入集离线跑对照，零依赖可用。

它遵守下面几条自己定的规矩：

1. **同一把尺子**。所有变体跑同一批输入，否则对照没有意义。
2. **离线可用**。不接后端，先在小样本上把话说明白，再去跑昂贵的评测。
3. **一次改一处**。同时改两个变体，就分不清是谁起的作用。

## 用法

```bash
python promptgarden.py --list --garden garden.json
python promptgarden.py --run --garden garden.json --inputs inputs.jsonl
```

加 `--json` 可以拿到机器可读的结果，便于接到流水线里。

## 已知局限

- 输出相似度用字符集合的 Jaccard，不做语义比较。
- 不调用模型，变体的输出由你自己填进来。
- 一次改多处就分不清是谁起的作用——工具会提示但不阻止。

## 跑测试

```bash
python test_promptgarden.py
```

测试用独立的断言与临时数据，不污染工作目录。

## 来源与参考

- Python 标准库文档：<https://docs.python.org/3/>
- GitHub 仓库：<https://github.com/gollerhey/promptgarden>

---

## 关于作者

gollerhey 做提示词变体的对照实验相关的问题。这个工具先替你回答一个具体问题，再谈别的。

- 个人主页：<https://gollerhey.github.io>
- 仓库：<https://github.com/gollerhey/promptgarden>

## 许可

MIT，见 [LICENSE](LICENSE)。
