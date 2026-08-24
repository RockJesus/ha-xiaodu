# 小度智能 Home Assistant 集成

将百度小度生态中的智能设备反向接入 Home Assistant，支持在 HA 中统一控制小度音箱、小度 APP 中绑定的所有智能家居设备（包括第三方设备）。

## 功能特性

- **Config Flow 可视化配置** — 无需编辑 YAML，在 HA 界面中完成全部配置
- **多设备类型支持**：
  - 💡 **灯** — 开关、亮度调节、色温调节、场景模式
  - 🔌 **开关/插座** — 通用开关、智能插座、各类电器
  - 🪟 **窗帘** — 开、关、停
  - ❄️ **空调** — 开关、温度设定、模式切换（制冷/制热/送风/除湿/自动）、风速调节
  - 🌡️ **传感器** — 温度、湿度、PM2.5、CO₂、TVOC、甲醛、空气质量等
  - 🌀 **风扇** — 开关、风速调节、摇头、模式切换
  - 🔐 **门锁** — 开关锁
  - 🔘 **按钮/场景** — 场景触发、晾衣架升降等
- **DataUpdateCoordinator 统一轮询** — 所有设备共享一次状态更新，降低 API 调用频率
- **Cookie 在线更新** — Cookie 过期后可在集成选项中直接更新，无需删除重配
- **晾衣架多面板支持** — 自动识别晾衣架的功能面板，创建独立开关和按钮实体

## 支持的 HA 版本

Home Assistant 2024.1.0 及以上版本（HAOS / Supervised / Container / Core 均可）

## 安装方法

### 方法一：手动安装（推荐）

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

### 方法二：HACS 安装

1. 在 HACS 中添加自定义仓库：`[https://github.com/xiaodu-ha/xiaodu](https://github.com/RockJesus/ha-xiaodu)`，类别选择「集成」
2. 在 HACS 集成列表中搜索「小度智能」并安装
3. 重启 Home Assistant

## 配置步骤

### 第一步：获取 BDUSS Cookie

1. 使用 Chrome / Edge 浏览器访问：https://xiaodu.baidu.com/saiya/smarthome/index.html
2. 使用你的百度账号登录（与小度 APP 同一账号）
3. 按 `F12` 打开开发者工具
4. 切换到「应用程序」(Application) 标签页
5. 左侧展开「Cookie」→ 点击 `https://xiaodu.baidu.com`
6. 在右侧表格中找到 `BDUSS` 字段，复制其完整值（很长的一串字符）

> **注意**：Cookie 有效期约 180 天，过期后设备会变为不可用状态，需重新获取并在集成选项中更新。

### 第二步：在 HA 中添加集成

1. 进入 HA「设置」→「设备与服务」→「添加集成」
2. 搜索「小度智能」或「xiaodu」
3. 在第一步中粘贴刚才复制的 `BDUSS` Cookie 值，点击提交
4. 选择要接入的家庭（如果有多个家庭）
5. 勾选要接入 HA 的设备（可多选），点击提交
6. 配置完成，设备将自动出现在 HA 中

### 第三步：更新 Cookie（过期后）

1. 进入「设置」→「设备与服务」→ 找到「小度智能」集成
2. 点击「配置」按钮
3. 输入新的 BDUSS Cookie，提交即可

## 工作原理

本集成通过百度小度开放平台的 Web API 与小度云端通信：

1. **鉴权** — 使用登录后的 `BDUSS` Cookie 进行身份验证
2. **设备发现** — 通过 `/saiya/smarthome/appliance` 接口获取用户绑定的设备列表
3. **状态查询** — 通过 `/saiya/smarthome/appliancedetails` 接口获取设备实时状态
4. **设备控制** — 通过 `/saiya/smarthome/directivesend` 接口发送 DuerOS 控制指令

所有设备状态通过 `DataUpdateCoordinator` 每 30 秒统一轮询一次。

## 已知限制

1. **Cookie 会过期** — 约 180 天有效期，需手动更新
2. **状态同步延迟** — 在小度 APP 或其他平台中操作设备后，HA 中的状态最多有 30 秒延迟（受轮询间隔限制）
3. **部分设备状态不回传** — 某些第三方厂商的设备在物理操作后不会向小度云端上报状态，导致 HA 中状态不同步（这是百度开放平台的限制）
4. **窗帘不支持位置控制** — 小度 API 仅支持开/关/停，不支持精确百分比位置
5. **空调直接设温兼容性** — 部分品牌空调可能不支持直接设定温度，会自动回退到逐度加减的方式

## 故障排查

### 设备显示为「不可用」

- 检查 Cookie 是否过期，尝试更新 Cookie
- 检查网络是否能正常访问 `xiaodu.baidu.com`
- 查看 HA 日志中的错误信息

### 配置时提示「Cookie 无效」

- 确认复制的是 `BDUSS` 字段的完整值，不要遗漏字符
- 确认登录的百度账号与小度 APP 使用的是同一账号
- 尝试在浏览器中退出重新登录后再次获取 Cookie

### 某些设备没有出现

- 确认该设备已在小度 APP 中正确添加并可以正常控制
- 部分设备类型可能尚未被支持，请查看「功能特性」中的支持列表
- 可以在配置时重新选择设备，或在 GitHub 提交 Issue 请求支持新设备类型

### 空调温度设定不准

- 部分品牌空调仅支持逐度加减，集成会自动计算差值并连续发送加减指令
- 如果设定后温度偏差较大，可能是空调本身的反馈延迟，等待一次轮询后状态会同步

## 文件结构

```
xiaodu_integration/
├── custom_components/
│   └── xiaodu/
│       ├── __init__.py          # 集成入口
│       ├── api.py               # 小度 API 封装
│       ├── appliance_types.py   # 设备类型映射
│       ├── config_flow.py       # 配置流程
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
│       └── translations/
│           └── zh-Hans.json     # 中文翻译
├── hacs.json                    # HACS 配置
├── LICENSE                      # MIT 许可证
└── README.md                    # 本文档
```

## 致谢

本集成参考了以下开源项目的实现思路：
- [hass_xiaodu](https://github.com/2331892928/hass_xiaodu)
- [hass-xiaodu](https://github.com/linrol/hass-xiaodu)

## 许可证

MIT License
