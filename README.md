# 小度智能 Home Assistant 集成

将百度小度生态中的智能设备**反向接入 Home Assistant**，在 HA 中统一控制小度音箱、小度 APP 中绑定的所有智能家居设备（包括第三方设备）。

<div align="center">

[![HACS Default](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://github.com/hacs/default)
[![最新版本](https://img.shields.io/github/v/release/RockJesus/ha-xiaodu)](https://github.com/RockJesus/ha-xiaodu/releases/latest)
[![HA 版本](https://img.shields.io/badge/Home%20Assistant-2024.1.0%2B-blue)](https://www.home-assistant.io/)
[![许可证](https://img.shields.io/github/license/RockJesus/ha-xiaodu)](LICENSE)

</div>

---

## ✨ 功能特性

- **Config Flow 可视化配置** — 无需编辑 YAML，在 HA 界面中完成全部配置
- **两种登录方式** — 支持**百度账号用户名密码登录**（按真实 wappass 登录协议自动完成，可填写 BAIDUID 提升成功率）与 **BDUSS Cookie 登录**
- **多设备类型支持**：
  - 💡 **灯** — 开关、亮度调节、色温调节、场景模式
  - 🔌 **开关/插座** — 通用开关、智能插座、洗衣机、热水器、净化器、加湿器、电饭煲、烤箱、微波炉、冰箱、燃气灶、油烟机、打印机、净水器、饮水机、咖啡机、智能马桶等
  - 🪟 **窗帘** — 开、关、停、精确位置（0-100%）
  - ❄️ **空调** — 开关、温度设定、模式切换（制冷/制热/送风/除湿/自动）、风速调节
  - 🌡️ **传感器** — 温度、湿度、PM2.5、PM10、CO₂、TVOC、甲醛、空气质量、TDS、噪音、电量等
  - 🌀 **风扇** — 开关、风速调节、摇头、模式切换
  - 🤖 **扫地机** — 开始清扫、暂停、停止、回充、状态与电量
  - 🔐 **门锁** — 开关锁
  - 🔘 **按钮/场景** — 场景触发、晾衣架升降等
- **DataUpdateCoordinator 统一轮询** — 所有设备共享一次状态更新，降低 API 调用频率
- **Cookie 在线更新** — Cookie 过期后可在集成选项中直接更新，无需删除重配
- **晾衣架多面板支持** — 自动识别晾衣架的功能面板，创建独立开关和按钮实体

---

## 📦 安装方法

### 方法一：通过 HACS 安装（推荐）

本集成已收录于 **HACS 官方默认仓库**，点击下方按钮即可在你的 Home Assistant 中直接打开 HACS 并一键安装：

[![在 HACS 中打开](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=RockJesus&repository=ha-xiaodu&category=integration)

> 按钮无法使用？也可手动操作：HACS → 集成 → 搜索「**小度智能**」→ 安装 → 重启 Home Assistant。

### 方法二：手动安装

<details>
<summary>展开手动安装步骤</summary>

1. 将 `custom_components/xiaodu` 文件夹复制到你的 HA 配置目录下：

   ```
   config/
   └── custom_components/
       └── xiaodu/
           ├── __init__.py
           ├── api.py
           ├── appliance_types.py
           ├── config_flow.py
           ├── const.py
           ├── coordinator.py
           ├── manifest.json
           ├── strings.json
           ├── light.py
           ├── switch.py
           ├── cover.py
           ├── climate.py
           ├── sensor.py
           ├── fan.py
           ├── lock.py
           ├── button.py
           └── translations/
               └── zh-Hans.json
   ```

2. 重启 Home Assistant

</details>

### ⚙️ 环境要求

> [!IMPORTANT]
> 需要 **Home Assistant 2024.1.0 及以上版本**（HAOS / Supervised / Container / Core 均可）。

---

## 🚀 配置步骤

### 第一步：添加集成并登录

进入 HA「设置」→「设备与服务」→「添加集成」，搜索「小度智能」或「xiaodu」，然后选择登录方式：

**方式 A：用户名密码登录（推荐）**

1. 选择「用户名密码登录」
2. 输入百度账号的用户名（手机号 / 邮箱）和密码（与小度 APP 同一账号）
3. **（可选，强烈建议）填写 BAIDUID**：在浏览器访问 `baidu.com` 后，按 `F12` 打开开发者工具 → 「应用程序」(Application) → Cookie → 复制 `BAIDUID` 字段的值（形如 `XXXX...:FG=1`）粘贴到「BAIDUID（可选）」输入框。填写后可显著提升成功率，避免百度风控的短信验证拦截
4. 登录成功后自动继续下一步

> [!NOTE]
> 用户名密码登录按百度 wappass 网页登录真实协议实现（RSA 加密 + 风控签名）。百度对登录有风控：若提示「百度风控要求验证」，请填写有效的 BAIDUID 后重试，或改用方式 B 的 Cookie 登录。

**方式 B：BDUSS Cookie 登录**

1. 使用 Chrome / Edge 浏览器访问：https://xiaodu.baidu.com/saiya/smarthome/index.html
2. 使用你的百度账号登录（与小度 APP 同一账号）
3. 按 `F12` 打开开发者工具
4. 切换到「应用程序」(Application) 标签页
5. 左侧展开「Cookie」→ 点击 `https://xiaodu.baidu.com`
6. 在右侧表格中找到 `BDUSS` 字段，复制其完整值（很长的一串字符）
7. 在集成中选择「Cookie 登录」，粘贴刚才复制的 `BDUSS` Cookie 值，点击提交

> [!NOTE]
> Cookie 有效期约 180 天，过期后设备会变为不可用状态，需重新获取并在集成选项中更新。

### 第二步：选择家庭与设备

1. 选择要接入的家庭（如果有多个家庭）
2. 勾选要接入 HA 的设备（可多选），点击提交
3. 配置完成，设备将自动出现在 HA 中

### 第三步：更新 Cookie（过期后）

1. 进入「设置」→「设备与服务」→ 找到「小度智能」集成
2. 点击「配置」按钮
3. 输入新的 BDUSS Cookie，提交即可

---

## 🔧 工作原理

本集成通过百度小度开放平台的 Web API 与小度云端通信：

1. **鉴权** — 使用登录后的 `BDUSS` Cookie 进行身份验证
2. **设备发现** — 通过 `/saiya/smarthome/appliance` 接口获取用户绑定的设备列表
3. **状态查询** — 通过 `/saiya/smarthome/appliancedetails` 接口获取设备实时状态
4. **设备控制** — 通过 `/saiya/smarthome/directivesend` 接口发送 DuerOS 控制指令

所有设备状态通过 `DataUpdateCoordinator` 每 30 秒统一轮询一次。

---

## ⚠️ 已知限制

1. **Cookie 会过期** — 约 180 天有效期，需手动更新
2. **状态同步延迟** — 在小度 APP 或其他平台中操作设备后，HA 中的状态最多有 30 秒延迟（受轮询间隔限制）
3. **部分设备状态不回传** — 某些第三方厂商的设备在物理操作后不会向小度云端上报状态，导致 HA 中状态不同步（这是百度开放平台的限制）
4. **部分窗帘型号不支持位置控制** — 设备未上报开合度（`degree`）时，仅支持开/关/停
5. **空调直接设温兼容性** — 部分品牌空调可能不支持直接设定温度，会自动回退到逐度加减的方式
6. **用户名密码登录可能触发风控** — 百度对登录请求有风控，无有效 BAIDUID 时可能要求短信验证（400023）；填写 BAIDUID 或改用 Cookie 登录可绕过

---

## 🛠 故障排查

### 设备显示为「不可用」

- 检查 Cookie 是否过期，尝试更新 Cookie
- 检查网络是否能正常访问 `xiaodu.baidu.com`
- 查看 HA 日志中的错误信息

### 配置时提示「Cookie 无效」

- 确认复制的是 `BDUSS` 字段的完整值，不要遗漏字符
- 确认登录的百度账号与小度 APP 使用的是同一账号
- 尝试在浏览器中退出重新登录后再次获取 Cookie

### 用户名密码登录失败 / 提示风控验证

- 确认账号密码正确，且该账号已登录过小度 APP 或小度网页版
- 百度对登录有风控：无有效 BAIDUID 时可能被要求短信验证（400023）。请在浏览器访问 `baidu.com` 后复制 Cookie 中的 `BAIDUID` 值（形如 `XXXX...:FG=1`），填入登录页的「BAIDUID（可选）」字段后重试
- 若始终无法通过验证，请改用「Cookie 登录」方式
- 密码登录成功后，集成已自动保存 BDUSS 用于后续访问，与 Cookie 方式等效

### 某些设备没有出现

- 确认该设备已在小度 APP 中正确添加并可以正常控制
- 部分设备类型可能尚未被支持，请查看「功能特性」中的支持列表
- 可以在配置时重新选择设备，或在 GitHub 提交 Issue 请求支持新设备类型

### 空调温度设定不准

- 部分品牌空调仅支持逐度加减，集成会自动计算差值并连续发送加减指令
- 如果设定后温度偏差较大，可能是空调本身的反馈延迟，等待一次轮询后状态会同步

---

## 📁 文件结构

```
xiaodu_integration/
├── custom_components/
│   └── xiaodu/
│       ├── __init__.py          # 集成入口
│       ├── api.py               # 小度 API 封装
│       ├── appliance_types.py   # 设备类型映射
│       ├── config_flow.py       # 配置流程（登录方式选择）
│       ├── login.py             # 百度账号用户名密码登录（wappass 真实协议）
│       ├── const.py             # 常量定义
│       ├── coordinator.py       # 数据协调器
│       ├── manifest.json        # 集成清单
│       ├── strings.json         # 英文字符串
│       ├── light.py             # 灯平台
│       ├── switch.py            # 开关平台
│       ├── cover.py             # 窗帘平台
│       ├── climate.py           # 空调平台
│       ├── sensor.py            # 传感器平台
│       ├── fan.py               # 风扇平台
│       ├── lock.py              # 门锁平台
│       ├── button.py            # 按钮平台
│       ├── vacuum.py            # 扫地机平台
│       └── translations/
│           └── zh-Hans.json     # 中文翻译
├── hacs.json                    # HACS 配置
├── LICENSE                      # MIT 许可证
└── README.md                    # 本文档
```

---

## ❤️ 致谢

本集成参考了以下开源项目的实现思路：
- [hass_xiaodu](https://github.com/2331892928/hass_xiaodu)
- [hass-xiaodu](https://github.com/linrol/hass-xiaodu)

## 📄 许可证

MIT License
