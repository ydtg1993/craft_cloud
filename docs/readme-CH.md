# CraftCloud v2.0

[![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/GUI-PySide6%2BQFluentWidgets-green)](https://doc.qt.io/qtforpython-6/)
[![Telegram API](https://img.shields.io/badge/Telegram-Telethon-0088cc)](https://telethon.dev/)
[![License](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE.txt)

**CraftCloud** 是一款将 Telegram 作为无限云存储的桌面客户端。提供类似网盘的界面，支持文件上传、下载、在线预览、目录管理以及本地文件夹自动同步。程序可最小化至系统托盘，后台静默运行同步任务，不影响前台工作。

---

## 界面预览
<table>
  <tr>
    <td><img width="300" src="https://cdn.jsdelivr.net/gh/ydtg1993/craft_cloud@main/docs/preview/preview-1.PNG"/></td>
    <td><img width="300" src="https://cdn.jsdelivr.net/gh/ydtg1993/craft_cloud@main/docs/preview/preview-2.PNG"/></td>
    <td><img width="300" src="https://cdn.jsdelivr.net/gh/ydtg1993/craft_cloud@main/docs/preview/preview-3.PNG"/></td>
  </tr>
</table>

## 功能特性

- 🔐 **Telegram 登录**
  扫码登录（QR Code），支持 API ID / API Hash。会话持久化，多账户支持，可随时登出。

- 🌐 **多语言支持**
  支持 6 种语言：中文、English、Français、Deutsch、Русский、한국어。设置页面实时切换。

- 📁 **文件管理**
  列表 / 图标双视图，拖拽移动（跨目录），批量删除 / 重命名 / 移动，属性查看。右键菜单支持上传、下载、新建文件夹等操作。

- 👀 **文件预览**
  支持图片、音频（带进度条）、视频、文本文件的在线预览，超过 100 MB 文件禁止预览。

- 📤 **上传与下载**
  文件或文件夹批量上传，可配置重试次数（默认 3 次）。下载进度实时显示，所有任务通过共享工作线程异步执行。

- 🔍 **智能搜索**
  按文件名模糊搜索。文件数 < 1 万时使用 SQL LIKE 查询；超过后自动启用 Whoosh 全文索引 + jieba 中文分词，兼顾效率与准确性。

- 📂 **目录与频道**
  应用内目录与 Telegram 频道自动绑定，支持多级子目录。频道失效或数据库记录丢失时可智能重建绑定。

- 🔄 **自动同步**
  添加本地文件夹，按分钟 / 小时 / 天定时同步到 Telegram 目录。窗口最小化到托盘时自动运行同步，恢复窗口时暂停。同步过程中自动维护本地与远程目录结构一致。

- 📊 **上传限制**
  可选启用的每日上传大小 / 数量限制，基于东八区（北京时间）统计。主页底部状态栏实时显示当日用量与限额的关系。关闭限制时，上限显示 ∞。

- 🧩 **任务队列**
  持久化任务历史表，展示上传 / 下载进度及同步状态，应用重启后记录保留。

- 🖥️ **系统托盘**
  关闭窗口最小化到托盘，同步自动恢复。右键菜单「打开网盘」/「退出程序」。双击托盘图标恢复窗口。

- 🎨 **现代界面**
  基于 QFluentWidgets，支持深色 / 浅色主题。同步根目录带有特殊图标标识。

- 📝 **日志系统**
  基于 loguru 的结构化日志 — 控制台 + 按天轮转文件，保留 7 天。Telethon 会话噪声已过滤。

---

> Telegram API 凭据申请：访问 [my.telegram.org](https://my.telegram.org/)，创建应用获取 `api_id` 和 `api_hash`。

## 架构

```
main.py          →  入口：配置初始化、登录 / 主窗口流程
core/            →  基础设施层（配置、数据库引擎、工作线程、任务路由）
model/           →  数据层（SQLAlchemy ORM 模型 + 仓库）
services/        →  业务逻辑层（上传、下载、搜索、同步、文件 CRUD）
view/            →  UI 层（PySide6 + QFluentWidgets，信号驱动）
```

应用采用**单一共享 Telegram 客户端**（`TgWorkerThread`）— 一个线程、一个事件循环、一个 `Telethon` 实例。所有操作（上传 / 下载 / 重命名 / 删除 / 预览）通过 `asyncio.run_coroutine_threadsafe()` 排队执行，按操作类型使用 `asyncio.Semaphore` 控制并发。

## 技术栈

| 类别 | 库 |
|------|-----|
| GUI | PySide6 ≥6.5, PySide6-Fluent-Widgets ≥1.11 |
| Telegram | Telethon ≥1.36, cryptg ≥0.4 |
| 数据库 | SQLAlchemy ≥2.0 (ORM), SQLite 3 (WAL 模式) |
| 配置 | Pydantic ≥2.0, PyYAML ≥6.0 |
| 日志 | loguru ≥0.7 |
| 搜索 | Whoosh ≥2.7, jieba ≥0.42 |
| 缓存 | diskcache ≥5.0 |
| 图像 | Pillow ≥9.0, qrcode ≥7.4 |
| 其他 | numpy <2 |

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 运行
python main.py
```

## 许可证

本项目基于 MIT 许可证开源。详见 [LICENSE.txt](LICENSE.txt)。

使用 Telegram 存储文件请遵守 Telegram 服务条款及相关法律法规。开发者不对因使用本工具产生的数据丢失或账号风险承担责任。

---

## 贡献

欢迎提交 Issue 或 Pull Request。

**感谢使用 CraftCloud！**
