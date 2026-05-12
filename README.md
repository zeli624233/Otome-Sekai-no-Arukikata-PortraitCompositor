![image](https://github.com/zeli624233/Otome-Sekai-no-Arukikata-PortraitCompositor/blob/main/logo2.png)
## 简介：
本项目是用于合成游戏“オトメ世界の歩き方”人物立绘的，该项目的诞生参考了很多大神的Github的库，在此一并感谢！
## 目前支持：
- オトメ世界の歩き方
- 何度目かのはじめまして
  > 游戏`何度目かのはじめまして`和`オトメ世界の歩き方`，存放人物立绘的目录，结构差不多，合成原理类似，因此增加支持。
  
  > 至于其他游戏，如果人物立绘的合成也是使用的是`PBD文件`和`TLG文件`的话，软件可能支持，总之，效果不敢保证。

## 主要功能：
### Ver1.0：

- 支持加载 `JSON 目录 + SINFO 目录 + PNG 目录`
- 自动识别姿势、身体服装、表情、红晕
- 右侧实时预览合成结果
- 导出当前 PNG
- 批量导出当前姿势全部组合
- 支持跳过“无表情”组合
- 支持 2 / 4 / 6 / 8 / 12 / 16 线程批量导出
- 可选择导出完成后自动打开文件夹
- 可作为 Python 模块被其他脚本调用
- Windows 打包时使用自定义程序图标，作用于窗口左上角、任务栏和后台进程图标
 ### Ver1.2：
 - 1.原生支持PBD文件及TLG文件的导入解析。
 该功能的实现,离不开：
- PBD 文件的处理：参考了zhaomaoniu大佬（ https://github.com/zhaomaoniu ）的代码
 PBDConverter：https://github.com/zhaomaoniu/PBDConverter 。
- TLG 文件的处理：参考了 rr- 大佬（ https://github.com/rr- ）的代码
tlg2png：https://github.com/vn-tools/tlg2png 。
> 在此一并感谢。
- 2.如果用户使用的是PBD文件及TLG文件输入的话，软件会解析并在软件目录下生成一个缓存目录，下一次用户再次选择该目录时，可直接调用。
- 3.如果监测到是PBD文件的解析时，需要游戏配置文件目录plugin下的文件，软件支持用户选择该游戏目录后，自动复制到软件目录中。
- 4.增加了多线程解析PBD文件和TLG文件的支持，如果你觉得解析很慢的话，可以试着提高解析的线程数。
- 5.加入了对游戏`何度目かのはじめまして`人物立绘的合成支持。
## 使用说明：
![image](https://github.com/zeli624233/Otome-Sekai-no-Arukikata-PortraitCompositor/blob/main/%E4%BD%BF%E7%94%A8%E8%AF%B4%E6%98%8E.png)
## 合成后的效果😋：
 - オトメ世界の歩き方のユイちゃん：
<div align="center">
  
  <img src="https://github.com/zeli624233/Otome-Sekai-no-Arukikata-PortraitCompositor/blob/main/%E3%83%A6%E3%82%A4%EF%BC%A2_2_export.png" width="450" />
  <img src="https://github.com/zeli624233/Otome-Sekai-no-Arukikata-PortraitCompositor/blob/main/st-la02_03_export.png" width="480" />
</div>

 - 何度目かのはじめましてのラプラ：


## 环境要求：

- Python 3.10+
- Windows 10/11 推荐
- 依赖：`Pillow`

安装依赖：

```bash
pip install -r requirements.txt
```

## 运行源码：

```bash
python main.py
```

Windows 也可以直接运行：

```bat
run_from_source.bat
```
## 许可证：

本项目使用 MIT License。详见 [LICENSE](LICENSE)。
# 感谢：

本项目是用于合成游戏 “オトメ世界の歩き方” 人物立绘的，该项目的诞生参考了很多大神的Github的库，在此一并感谢！

- PSB 文件转换成 JSON 文件
  参考了zhaomaoniu大佬（ https://github.com/zhaomaoniu ）的代码，非常感谢，曾一度以为没办法转换呢，幸好有大佬的仓库！：（ https://github.com/zhaomaoniu/PBDConverter ）

- TLG 文件转换成 PNG  文件
  参考了rr- 大佬（ https://github.com/rr- ）的代码，使用批处理脚本，真快！，不用手动复制了！：（ https://github.com/vn-tools/tlg2png ）

- XP3 游戏资源的解包
  离不开YeLikesss大佬（ https://github.com/YeLikesss ）的KrkrExtractV2 (ForCxdecV2) 动态工具集，对付加密的 Cxdec V2游戏真有一手！：（ https://github.com/YeLikesss/KrkrExtractForCxdecV2 ）

- 游戏原文件文件名的还原
  离不开UlyssesWu大佬（ https://github.com/UlyssesWu ）的FreeMote工具，有文件的哈希值配合这个工具，游戏的文件原名轻松找到！：（ https://github.com/UlyssesWu/FreeMote ）










