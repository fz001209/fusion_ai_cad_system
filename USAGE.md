# Fusion AI CAD System 使用指南

## 快速开始

### 运行完整流程

```powershell
# 1. 从 YAML 需求生成建模计划
python tools/run_pipeline.py --source-anforderungsliste input/final_1.yaml

# ✅ 默认行为（无需额外参数）
# - 自动生成时间戳 Run ID（目录：execution/runs/<timestamp>/）
# - 默认启用 LLM 规划开关：
#   - 若未设置 OPENAI_API_KEY：LLM 不会被调用，系统会以确定性规则继续（并提示 [WARN]）
#   - 若已设置 OPENAI_API_KEY：Agent4 的 LLM 调用失败会让 pipeline 直接失败（不再静默回退）
#   - Agent2 的 LLM 主要用于推断 connection_placements（阵列语义/孔落点语义），且只在发现缺失 placements 时按需调用
# - 自动执行放置 DoD 校验（tools/validate_placement_dod.py）；失败会让 pipeline 直接退出非 0

# 或使用另一份示例输入
python tools/run_pipeline.py --source-anforderungsliste input/anforderungsliste.yaml

# 2. 在 Fusion 360 中手动执行建模
# 打开 Fusion 360 → Scripts and Add-Ins → 运行 fusion_api_server/fusion_api_server.py
# 读取 execution/runs/<run_id>/fusion_manual_plan.json

# 3.（标准件本地库）把下载模型放到以下路径之一，然后重建索引
# fastener: part_library/cad/fasteners/<kind>/<standard>/<size>/<length>/<lod>/<file>
#   例：part_library/cad/fasteners/bolt/ISO4017/M3/L10/simplified/bolt_ISO4017_M3_L10_s.f3d
# bearing: part_library/cad/bearings/<series>/<designation_or_id_od_w>/<lod>/<file>
#   例：part_library/cad/bearings/deep_groove/608/simplified/bearing_608_s.f3d
python tools/build_parts_index.py
```

### 常用参数

```powershell
# 关闭 LLM 高层推理（使用确定性规划）
python tools/run_pipeline.py \
  --source-anforderungsliste input/my_model.yaml \
  --no-use-llm-strategy \
  --no-use-llm-assembly-intent

# 指定 Run ID
python tools/run_pipeline.py \
  --source-anforderungsliste input/my_model.yaml \
  --run-id my_custom_run_name

# 若 run-id 已存在，不会报错；会自动追加后缀（例如 my_custom_run_name_2）
```

---

## 输入需求文件

### YAML 格式

系统使用结构化 YAML 描述建模需求：

```yaml
# input/my_robot_module.yaml

use_case: 楼梯攀爬机器人
module: 三星轮模块（Tri-Star Wheel Module）

description: >
  三星轮模块由一个中心轮毂、三根轮臂、三个轮子和上下两片载体板组成。
  上下两片载体板（carrier plate）分别夹在轮臂的两侧，与轮毂连接。

geometry_parameters_mm:
  # 全局尺寸（单位：毫米）
  wheel_center_radius: 60           # 轮心位置半径
  arm_length: 60                    # 轮臂长度
  arm_width: 14                     # 轮臂宽度
  center_hub_outer_radius: 14       # 中心轮毂外径
  carrier_plate_thickness: 6        # 载体板厚度
  
  # 组件尺寸
  hub:
    radius: 14
    thickness: 6
  
  arm:
    length: 60
    width: 14
    thickness: 6
  
  wheel:
    outer_radius: 30
    inner_radius: 6
    thickness: 8

structure:
  # 组件层级结构
  hub:
    position: [0, 0, 0]
    
  arms:
    count: 3
    angular_spacing: 120  # 度
    parent: hub
    
  wheels:
    count: 3
    parent: arms  # 每个轮子附在对应的轮臂上
    
  carrier_plates:
    count: 2
    type: rounded_triangle_3arm  # 特殊几何类型
    parent: hub
    positions:
      - [0, 0, -3]  # 上载体板
      - [0, 0, 9]   # 下载体板
```

### 关键字段说明

| 字段 | 说明 | 必需 |
|------|------|------|
| `use_case` | 高层应用场景（用于对象类型识别：robot/furniture/aircraft）| 是 |
| `module` | 模块名称 | 是 |
| `description` | 自然语言描述 | 是 |
| `geometry_parameters_mm` | 所有尺寸参数（单位：mm）| 是 |
| `structure` | 组件层级结构 | 推荐 |

---

## 环境配置

### 环境变量

在根目录创建 `.env` 文件（系统自动加载）：

```bash
# .env

# OpenAI API（用于 LLM 规划）
OPENAI_API_KEY=sk-your_api_key_here
OPENAI_MODEL=gpt-4o-mini                   # 可选

# 可选：网络较慢/偶发超时时可调大
OPENAI_TIMEOUT_SECONDS=180                 # 可选（默认 180）
OPENAI_MAX_RETRIES=2                       # 可选（默认 2）

# Pipeline 配置
DEFAULT_EXECUTOR=dryrun                    # 可选

# 初始放置（Agent3a）
# 指定哪个 component 作为 grounded root（不指定则按启发式选择，如 central_hub/base/frame）
FUSION_GROUND_COMPONENT_ID=central_hub      # 可选
```

或临时在 PowerShell 会话设置：

```powershell
$env:OPENAI_API_KEY = "sk-..."
$env:OPENAI_MODEL = "gpt-4o-mini"

# 可选：网络较慢/偶发超时时可调大
$env:OPENAI_TIMEOUT_SECONDS = "180"
$env:OPENAI_MAX_RETRIES = "2"
```

### Python 环境

```powershell
# 创建虚拟环境
python -m venv .venv

# 激活
.venv\Scripts\Activate.ps1  # Windows
# 或
source .venv/bin/activate  # Linux/Mac

# 安装依赖
pip install -r requirements.txt
```

---

## 输出文件结构

每次运行生成独立目录：`execution/runs/<run_id>/`

```
execution/runs/tri_star_20260201_223607/
├── input/
│   └── anforderungsliste.yaml          # 输入需求（快照）
│
├── knowledge/
│   └── knowledge_graph.json            # 知识图谱
│
├── planning/
│   ├── geometry_semantics_round_1.json # 几何语义（第 1 轮）
│   ├── shape_realization_round_1.json  # 策略计划（第 1 轮）
│   ├── geometry_plan_round_1.json      # 几何步骤（第 1 轮）
│   ├── assembly_semantics_round_1.json # 装配语义（第 1 轮）
│   ├── function_plan_round_1.json      # 函数计划（归档）
│   ├── function_plan.json              # 函数计划（当前）
│   ├── planner_llm_strategy_round_1.json       # LLM 策略决策审计（可选）
│   └── planner_llm_assembly_round_1.json       # LLM 装配意图审计（可选）
│
│   └── errors/
│       ├── placement_injection_report.json     # DoD 校验生成的放置注入报告（placed/skipped+reason）
│       └── shape_realization_missing_anchor.json  # Agent3a 特征锚点缺失错误（如孔 anchoring 不满足契约）
│
├── execution/
│   ├── context.json                    # 执行上下文
│   ├── resolved_steps.json             # 解析后的步骤
│   └── execution_trace.json            # 执行跟踪（⭐ 调试用）
│
├── memory/
│   └── run_memory.json                 # Run 记忆（学习数据，可选）
│
├── fusion_manual_plan.json             # Fusion 执行输入（⭐）
├── metadata.json                        # Run 元数据
└── events.jsonl                         # 事件日志（追加写）
```

### 关键文件说明

#### `function_plan.json`（最终可执行计划）

```json
{
  "metadata": {
    "plan_id": "tri_star_20260201_223607_function_plan_round_1",
    "schema_version": "1.0",
    "created_at": "2026-02-01T22:36:07"
  },
  "steps": [
    {
      "id": "create_hub",
      "function": "CREATE_COMPONENT",
      "inputs": {
        "name": "hub",
        "parent_component_id": null
      },
      "capture": {
        "vars": {
          "hub_component_id": "component_id",
          "hub_occurrence_id": "occurrence_id"
        }
      }
    },
    ...
  ]
}
```

#### `execution_trace.json`（执行跟踪）

查看每个步骤的执行结果和输出：

```json
{
  "steps": [
    {
      "id": "create_hub",
      "function": "CREATE_COMPONENT",
      "status": "success",
      "outputs": {
        "component_id": "Component_hub_abc123",
        "occurrence_id": "Occurrence_hub_def456"
      },
      "timestamp": "2026-02-01T22:37:00"
    },
    ...
  ]
}
```

## 常见问题

### Q: Pipeline 运行后在哪里找到 3D 模型？

**A**: Pipeline 生成计划文件（`function_plan.json` 和 `fusion_manual_plan.json`），需要：
1. 打开 Fusion 360
2. 运行 `fusion_api_server/fusion_api_server.py` 脚本
3. 脚本会自动执行建模（如需导出请手动处理）

---

### Q: 如何查看执行了哪些步骤？

**A**: 查看 `execution/execution_trace.json`，包含每个步骤的：
- 函数名称
- 输入参数
- 输出结果
- 执行状态
- 时间戳

---

### Q: 如何调试规划失败？

**A**: 按顺序检查：
1. **`events.jsonl`**：搜索失败事件
2. **`execution/execution_trace.json`**：查看具体步骤失败原因

示例 events.jsonl 查找失败：

```powershell
Select-String -Path "execution/runs/<run_id>/events.jsonl" -Pattern "status.*failed"
```

### Q: 系统如何学习和改进？

**A**: 可选运行 Agent5 的 memory snapshot 子过程，生成 `memory/run_memory.json`，记录：
- **成功的参数偏好**：每个函数的 multiplier
- **成功的策略**：component_based vs single_body

后续运行会自动读取记忆，优先使用历史成功的策略。

---

### Q: 支持哪些几何特征？

**A**: 当前支持（见 `functions/functions.json`）：

| 函数 | 功能 |
|------|------|
| `CREATE_COMPONENT` | 创建组件（支持多层级装配）|
| `CREATE_SKETCH_ON_PLANE` | 在 XY/XZ/YZ 平面创建草图 |
| `SKETCH_CIRCLE` | 圆形草图 |
| `SKETCH_RECTANGLE` | 矩形草图 |
| `SKETCH_ROUNDED_POLYGON` | 参数化圆角多边形（三臂载体板等）|
| `EXTRUDE_NEW_BODY` | 拉伸创建实体 |
| `EXTRUDE_CUT` | 拉伸切除 |
| `REVOLVE_NEW_BODY` | 旋转创建实体 |
| `RIGID_MATE_FACES` | 刚性配合约束 |

**待扩展**：圆角、倒角、孔、阵列、镜像、扫描、放样、布尔运算等。

---

### Q: 如何添加新的几何特征函数？

**A**: 详见 [README.md - 扩展开发](README.md#扩展开发)

简要步骤：
1. 在 `functions/functions.json` 定义函数规范
2. 在 `fusion_api_server/modeling.py` 实现 Fusion API 调用
3. （可选）在 `agents/Agent2_plan_geometry_semantic/transform.py` 或 `agents/Agent3b_compile_geometry_plan/transform.py` 添加生成逻辑

---

### Q: 如何控制建模策略？

**A**: 系统根据 `intent` 字段自动识别对象类型：

| intent 关键词 | 对象类型 | 建模策略 | 说明 |
|--------------|---------|---------|------|
| robot, 机器人, 机械 | robot | component_based | 每个组件独立创建 |
| furniture, 家具, 桌椅 | furniture | single_body | 单体建模 |
| aircraft, 飞行器 | aircraft | component_based | 多组件装配 |
| 其他 | generic | single_body | 默认策略 |

示例：

```yaml
use_case: 楼梯攀爬机器人  # → robot → component_based
```

---

### Q: 单位是什么？

**A**: **系统契约**：
- **输入层（YAML/Plan）**：所有尺寸单位为**毫米（mm）**
- **Fusion API**：内部转换为**厘米（cm）**
- **转换层**：`FusionApiController` 自动处理，用户无需关心

示例：

```yaml
geometry_parameters_mm:
  hub:
    radius: 14  # 14 毫米
```

系统自动转换为 `1.4 cm` 供 Fusion API 使用。

---

### Q: 如何查看完整的事件日志？

**A**: 查看 `events.jsonl`：

```powershell
# 查看所有事件
Get-Content "execution/runs/<run_id>/events.jsonl"

# 过滤失败事件
Select-String -Path "execution/runs/<run_id>/events.jsonl" -Pattern "failed"

# 过滤特定 Agent
Select-String -Path "execution/runs/<run_id>/events.jsonl" -Pattern "plan_geometry_semantic|shape_realization_planner_3a|compile_geometry_plan_3b"
```

---

### Q: 为什么有 `planner_llm_strategy_round_1.json` 和 `planner_llm_assembly_round_1.json`？

**A**: 这些是 **LLM 高层推理审计文件**（可选功能）：

- **`planner_llm_strategy_round_1.json`**：LLM 策略决策（component_based vs single_body）
- **`planner_llm_assembly_round_1.json`**：LLM 装配意图推理

关闭 LLM 推理：

```powershell
python tools/run_pipeline.py \
  --no-use-llm-strategy \
  --no-use-llm-assembly-intent ...
```

---

## 参考文档

- **[README.md](README.md)**：系统概述与架构
- **[QUICK_REFERENCE.md](QUICK_REFERENCE.md)**：命令速查
- **[FUSION_API_SETUP.md](FUSION_API_SETUP.md)**：Fusion 360 配置
- **[functions/README.md](functions/README.md)**：能力层设计
- **[docs/START_HERE.md](docs/START_HERE.md)**：深入文档

---

**最后更新**：2026-02-01
