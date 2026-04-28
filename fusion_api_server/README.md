# Fusion API Server

Fusion 360 端的 CAD 执行引擎，负责将 AI 生成的几何计划转换为实际的 3D 模型。

---

## 概述

Fusion API Server 是一个运行在 Fusion 360 内部的 Python 脚本系统，通过 Fusion 360 API 执行由 AI 生成的几何操作计划（`fusion_manual_plan.json`），自动化完成 3D 建模与装配流程。

### 核心功能

- ✅ **自动化建模** - 从 JSON 计划文件驱动 Fusion 360 API 执行几何操作
- ✅ **多层级装配** - 支持父子组件关系和局部坐标系变换
- ✅ **单位自动转换** - 统一使用毫米（mm），自动转换为 Fusion API 所需的厘米（cm）
- ✅ **变量解析** - 支持 `${variable_name}` 变量引用和自动替换
- ✅ **后处理占位** - 当前无自动导出/渲染
- ✅ **错误跟踪** - 完整的执行状态标记和错误日志

---

## 文件结构

```
fusion_api_server/
├── fusion_api_server.py      # 主入口（Fusion 360 脚本入口点）
├── orchestrator.py            # 执行流程编排器（核心调度逻辑）
├── modeling.py                # Fusion API 建模控制器（所有CAD操作）
├── plan_io.py                 # 计划文件加载和定位
├── marker_io.py               # 状态标记文件写入
├── postprocess.py             # 后处理（当前无自动导出/渲染）
├── fusion_api_server.manifest # Fusion 360 脚本清单
└── README.md                  # 本文档
```

---

## 架构设计

### 1. 执行流程

```
用户运行 Fusion 脚本
    ↓
fusion_api_server.py::run()
    ↓
orchestrator.py::run_once()
    ├─ plan_io.py::resolve_plan_path()  # 定位计划文件
    ├─ marker_io.py::write_started()    # 写入启动标记
    ├─ orchestrator.py::dispatch_plan() # 执行建模计划
    │   ├─ 变量解析（${var_name}）
    │   ├─ 动态调用 modeling.py 方法
    │   └─ 维护 execution_context
    ├─ postprocess.py::run_all()        # 后处理（当前无自动导出/渲染）
    └─ marker_io.py::write_done()       # 写入完成标记
```

### 2. 模块职责

#### **fusion_api_server.py** - 脚本入口
- Fusion 360 识别的脚本入口点
- 提供 `run(context)` 函数
- 捕获顶层异常并写入错误日志
- 调用 `orchestrator.run_once()`

#### **orchestrator.py** - 执行编排器
- 负责整个执行流程的编排
- 定位和加载 `fusion_manual_plan.json`
- 变量解析：`${variable_name}` → 实际值
- 动态方法调度：从 JSON 中的 `function` 字段调用 `modeling.py` 对应方法
- 维护 `execution_context`：存储所有步骤的返回值
- 进度对话框管理

**关键函数**:
- `run_once(app, ui)` - 主执行入口
- `dispatch_plan(controller, steps, ui, progress)` - 计划调度器
- `_resolve_variables(obj, context)` - 递归变量替换

#### **modeling.py** - Fusion API 控制器
- 包含所有 CAD 建模操作的实现
- 所有方法名与 JSON 计划中的 `function` 字段一致
- 单位转换：所有输入参数为毫米（mm），内部转换为厘米（cm）
- ID 管理：维护 component_id、sketch_id、profile_id、body_id 映射

**核心类**:
```python
class FusionApiController:
    def __init__(self, app: adsk.core.Application)
    
    # 单位转换工具
    def mm(value_mm: float) -> ValueInput
    def cm_vec(x_mm, y_mm, z_mm) -> Vector3D
    def cm_point(x_mm, y_mm, z_mm) -> Point3D
    
    # 建模操作（方法名与 function_name 一致）
    def CREATE_COMPONENT(name, parent_component_id, transform)
    def ACTIVATE_COMPONENT(component_id)
    def CREATE_SKETCH_ON_PLANE(component_id, plane, name)
    def SKETCH_CIRCLE(sketch_id, center, radius, construction)
    def SKETCH_RECTANGLE(sketch_id, center, width, height, construction)
    def SKETCH_ROUNDED_POLYGON(sketch_id, center, hub_radius, arm_count, ...)
    def EXTRUDE_NEW_BODY(component_id, profile_id, distance, direction, draft_angle)
    def EXTRUDE_CUT(component_id, profile_id, distance)
    def REVOLVE_NEW_BODY(component_id, profile_id, axis, angle_rad)
    def CREATE_REVOLUTE_JOINT(occ1_name, occ2_name, axis)
```

#### **plan_io.py** - 计划文件加载
- 定位和加载 `fusion_manual_plan.json`
- 支持多种查找策略：
  1. 环境变量 `FUSION_PLAN_PATH`
  2. 最新的 `execution/runs/<run_id>/fusion_manual_plan.json`
- 解析 run_dir 路径

**关键函数**:
```python
def find_repo_root() -> Path
def find_latest_run_dir(repo_root) -> Path
def resolve_plan_path(repo_root) -> Path
def load_plan(plan_path) -> dict
def derive_run_dir(plan_path) -> Path
```

#### **marker_io.py** - 状态标记文件
- 写入执行状态标记文件（JSON 格式）
- 所有写入操作均为 best-effort（失败不影响主流程）

**标记文件**:
- `fusion_started.json` - 脚本启动标记
- `fusion_done.json` - 执行完成标记
- `fusion_failed.json` - 执行失败标记（包含 traceback）
- `fusion_warnings.json` - 警告日志（数组）

**关键函数**:
```python
def write_started(run_dir, plan_path, plan_summary)
def write_done(run_dir, artifacts, timestamps)
def write_failed(run_dir, traceback_text) -> str  # 返回写入路径
def append_warning(run_dir, warning_text)
```

#### **postprocess.py** - 后处理
- 当前为占位实现（无自动导出/渲染）

**关键函数**:
```python
def run_export(run_dir)
def run_all(run_dir, ui, enable_export, strict_mode)
```

---

## 关键设计原则

### 1. ID 命名规则（系统契约）

所有实体 ID 遵循严格的命名约定：

| ID 类型 | 格式 | 示例 | 说明 |
|---------|------|------|------|
| `component_id` | `<name>` | `hub`, `arm_1` | 组件名称 |
| `occurrence_id` | `<name>` | `hub`, `arm_1` | 出现实例ID（与component_id相同）|
| `sketch_id` | `<component_id>:<sketch_name>` | `hub:sketch_hub` | Sketch标识 |
| `profile_id` | `<sketch_id>:profile:<index>` | `hub:sketch_hub:profile:0` | Profile标识 |
| `body_id` | `<component_id>:body:<index>` | `hub:body:0` | Body标识 |

### 2. 单位系统（CRITICAL）

**统一单位约定**：
- ✅ JSON 计划中所有尺寸/坐标/长度 = **毫米（mm）**
- ✅ Fusion 360 API 内部使用 = **厘米（cm）**
- ✅ 自动转换：`mm → cm`（除以 10.0）

**转换工具函数**：
```python
# 单个尺寸转换（用于 distance、radius 等）
dist = self.mm(6.0)  # 6mm → 0.6cm ValueInput

# 坐标向量转换（用于 translation、sketch point）
vec = self.cm_vec(14.0, 60.0, 0.0)  # [1.4, 6.0, 0.0] cm

# 坐标点转换（用于 sketch 几何）
pt = self.cm_point(0, 0, 0)  # Point3D(0, 0, 0) cm
```

**无临时判断**：
- ❌ 禁止使用 `if distance > 100: distance /= 10`
- ✅ 所有转换通过 `mm()` / `cm_vec()` / `cm_point()` 统一完成

### 3. 坐标系约定

**局部坐标系（Local Transform）**：
```python
# CREATE_COMPONENT 的 transform.translation 是相对父组件的局部坐标
{
  "function": "CREATE_COMPONENT",
  "inputs": {
    "name": "arm_1",
    "parent_component_id": "hub",  # 父组件
    "transform": {
      "translation": {
        "x": 44.0,  # mm，相对 hub 局部坐标系
        "y": 0.0,
        "z": 0.0
      }
    }
  }
}
```

- 当 `parent_component_id` 存在时，`translation` 是相对父组件的**局部坐标**
- 当 `parent_component_id` 为 `null` 时，`translation` 是相对 root（即**世界坐标**）
- Fusion 360 会自动计算实际世界位置（通过父组件的变换矩阵）

### 4. 变量解析系统

**变量引用格式**：`${variable_name}`

**解析过程**：
```python
# 输入（JSON）
{
  "function": "EXTRUDE_NEW_BODY",
  "inputs": {
    "component_id": "${hub_component_id}",     # 变量引用
    "profile_id": "${hub_profile_id}",         # 变量引用
    "distance": 20
  }
}

# 解析后（实际调用）
{
  "function": "EXTRUDE_NEW_BODY",
  "inputs": {
    "component_id": "hub",                     # 已解析
    "profile_id": "hub:sketch_hub:profile:0",  # 已解析
    "distance": 20
  }
}
```

**变量来源**：
1. **步骤返回值**：每个步骤的返回值自动加入 `execution_context`
2. **capture 字段**：显式捕获返回值的特定字段
```json
{
  "id": "create_hub",
  "function": "CREATE_COMPONENT",
  "capture": {
    "vars": {
      "hub_component_id": "component_id",  # 捕获 component_id → hub_component_id
      "hub_occurrence_id": "occurrence_id"
    }
  }
}
```

**兜底机制**：
- 如果变量未找到，尝试使用最近的通用输出
- 例如：`${hub_profile_id}` 未找到时，尝试 `${last_profile_id}`

### 5. Profile 动态解析

**问题**：Fusion API 的 Profile 对象在 Sketch 修改后会失效

**解决方案**：
- ❌ 不存储 Profile 对象引用
- ✅ 存储 `profile_id` 字符串（格式：`<sketch_id>:profile:<index>`）
- ✅ 在 EXTRUDE 时动态从 Sketch 查询 Profile

**实现**：
```python
# SKETCH_CIRCLE 不存储 profile 对象
def SKETCH_CIRCLE(self, sketch_id, center, radius, construction):
    sketch = self._sketches[sketch_id]
    circle = sketch.sketchCurves.sketchCircles.addByCenterRadius(...)
    
    # 生成 profile_id（不存储对象）
    counter = self._profile_counter.get(sketch_id, 0)
    profile_id = f"{sketch_id}:profile:{counter}"
    self._profile_counter[sketch_id] = counter + 1
    return {"profile_id": profile_id}

# EXTRUDE 动态查询 profile
def EXTRUDE_NEW_BODY(self, component_id, profile_id, distance, ...):
    # 从 profile_id 提取 sketch_id
    sketch_id = profile_id.split(":profile:", 1)[0]
    sketch = self._sketches[sketch_id]
    
    # 动态查询 profile（使用第一个 profile，通常是外轮廓）
    profile = sketch.profiles.item(0)
    
    # 使用 profile 进行拉伸
    ...
```

---

## 使用方法

### 1. 在 Fusion 360 中运行

**步骤**：

1. **打开 Fusion 360**

2. **导航到脚本管理器**：
   - `工具` → `脚本和加载项` → `脚本`

3. **添加脚本**：
   - 点击 `+` 按钮
   - 选择 `fusion_api_server` 文件夹

4. **运行脚本**：
   - 选中 `fusion_api_server`
   - 点击 `运行`

5. **自动执行**：
   - 脚本会自动定位最新的 `fusion_manual_plan.json`
   - 执行所有建模步骤
  - 完成后结束执行

### 2. 环境变量（可选）

```bash
# 指定计划文件路径（优先级最高）
FUSION_PLAN_PATH=D:/Fan/fusion_ai_cad_system/execution/runs/20260202_115003/fusion_manual_plan.json

# 指定 run_id（用于定位 run_dir）
FUSION_RUN_ID=20260202_115003
```

### 3. 计划文件格式

**fusion_manual_plan.json 示例**：
```json
{
  "metadata": {
    "plan_id": "20260202_115003_geometry_plan_1",
    "schema_version": "1.0",
    "created_at": "2026-02-02T11:51:08"
  },
  "steps": [
    {
      "id": "create_hub",
      "function": "CREATE_COMPONENT",
      "inputs": {
        "name": "hub",
        "parent_component_id": null,
        "transform": null
      },
      "capture": {
        "vars": {
          "hub_component_id": "component_id",
          "hub_occurrence_id": "occurrence_id"
        }
      }
    },
    {
      "id": "activate_hub",
      "function": "ACTIVATE_COMPONENT",
      "inputs": {
        "component_id": "${hub_component_id}"
      },
      "depends_on": ["create_hub"]
    },
    {
      "id": "sketch_hub",
      "function": "CREATE_SKETCH_ON_PLANE",
      "inputs": {
        "component_id": "${hub_component_id}",
        "plane": {"type": "XY"},
        "name": "sketch_hub"
      },
      "depends_on": ["activate_hub"]
    },
    {
      "id": "circle_hub",
      "function": "SKETCH_CIRCLE",
      "inputs": {
        "sketch_id": "${hub_sketch_id}",
        "center": {"x": 0, "y": 0},
        "radius": 25,
        "construction": false
      },
      "capture": {
        "vars": {
          "hub_profile_id": "profile_id"
        }
      }
    },
    {
      "id": "extrude_hub",
      "function": "EXTRUDE_NEW_BODY",
      "inputs": {
        "component_id": "${hub_component_id}",
        "profile_id": "${hub_profile_id}",
        "distance": 20,
        "direction": "positive"
      }
    }
  ]
}
```

---

## 支持的建模操作

### 组件操作

| 函数名 | 参数 | 返回值 | 说明 |
|--------|------|--------|------|
| `CREATE_COMPONENT` | `name`, `parent_component_id`, `transform` | `{component_id, occurrence_id}` | 创建新组件或子组件 |
| `ACTIVATE_COMPONENT` | `component_id` | `{}` | 激活组件（使其成为当前编辑对象）|

### Sketch 操作

| 函数名 | 参数 | 返回值 | 说明 |
|--------|------|--------|------|
| `CREATE_SKETCH_ON_PLANE` | `component_id`, `plane`, `name` | `{sketch_id}` | 在指定平面创建 Sketch |
| `SKETCH_CIRCLE` | `sketch_id`, `center`, `radius`, `construction` | `{profile_id}` | 画圆 |
| `SKETCH_RECTANGLE` | `sketch_id`, `center`, `width`, `height`, `construction` | `{profile_id}` | 画矩形 |
| `SKETCH_ROUNDED_POLYGON` | `sketch_id`, `center`, `hub_radius`, `arm_count`, `arm_length`, `arm_width`, `corner_radius`, `construction` | `{profile_id, curve_ids}` | 画圆角多边形（如三臂板）|

### 特征操作

| 函数名 | 参数 | 返回值 | 说明 |
|--------|------|--------|------|
| `EXTRUDE_NEW_BODY` | `component_id`, `profile_id`, `distance`, `direction`, `draft_angle` | `{body_id}` | 拉伸创建新实体 |
| `EXTRUDE_CUT` | `component_id`, `profile_id`, `distance` | `{}` | 拉伸切除 |
| `REVOLVE_NEW_BODY` | `component_id`, `profile_id`, `axis`, `angle_rad` | `{}` | 旋转创建新实体 |

### 装配操作

| 函数名 | 参数 | 返回值 | 说明 |
|--------|------|--------|------|
| `CREATE_REVOLUTE_JOINT` | `occ1_name`, `occ2_name`, `axis` | `{}` | 创建旋转关节 |

---

## 状态标记文件

### fusion_started.json
```json
{
  "status": "started",
  "plan_path": "D:/Fan/fusion_ai_cad_system/execution/runs/20260202_115003/fusion_manual_plan.json",
  "plan_summary": {
    "step_count": 45,
    "functions": ["CREATE_COMPONENT", "ACTIVATE_COMPONENT", "CREATE_SKETCH_ON_PLANE", ...]
  }
}
```

### fusion_done.json
```json
{
  "status": "done",
  "artifacts": {},
  "timestamps": {
    "finished": "2026-02-02T12:05:30"
  }
}
```

### fusion_failed.json
```json
{
  "status": "failed",
  "traceback": "Traceback (most recent call last):\n  File ...\n  ..."
}
```

### fusion_warnings.json
```json
[
  {"warning": "用户在建模阶段取消"},
  {"warning": "后处理已跳过"}
]
```

---

## 错误处理

### 1. 多级错误捕获

**层级1：顶层入口** (`fusion_api_server.py::run()`)
- 捕获所有未处理异常
- 写入 `fusion_failed.json`
- 弹窗提示用户

**层级2：执行流程** (`orchestrator.py::run_once()`)
- 捕获计划加载失败
- 捕获建模执行失败
- 捕获后处理失败
- 分别记录到 warnings 或 failed

**层级3：步骤执行** (`orchestrator.py::dispatch_plan()`)
- 捕获单个步骤失败
- 包含步骤ID和函数名的详细错误信息
- 立即中止执行

### 2. 错误日志写入策略

`marker_io.write_failed()` 会尝试按优先级写入多个位置：

1. `<run_dir>/fusion_failed.json` （优先）
2. 当前工作目录 `./fusion_failed.json`
3. 脚本目录 `fusion_api_server/fusion_failed.json`
4. 用户临时目录 `%TEMP%/fusion_failed.json`
5. 用户 AppData `%APPDATA%/fusion_failed.json`

**返回值**：成功写入的路径，失败返回 `None`

### 3. Best-Effort 原则

所有 `marker_io` 写入操作均为 best-effort：
- 写入失败不影响主流程
- 所有写入操作包裹在 `try-except` 中
- 异常被静默忽略（`pass`）

---

## 调试技巧

### 1. 查看执行日志

**方法1：Fusion 360 日志**
- `帮助` → `显示文本命令窗口`
- 查看 `print()` 输出

**方法2：状态标记文件**
- 检查 `fusion_started.json` - 确认脚本已启动
- 检查 `fusion_done.json` - 确认执行完成
- 检查 `fusion_failed.json` - 查看错误堆栈
- 检查 `fusion_warnings.json` - 查看警告信息

### 2. 变量调试

在 `orchestrator.py::dispatch_plan()` 中添加打印：
```python
log(f"Inputs (resolved): {json.dumps(inputs_dict, indent=2, ensure_ascii=False)}")
log(f"Result: {result}")
```

### 3. 单步调试

注释掉后续步骤，只执行前几步：
```json
{
  "steps": [
    // ... 保留前3步
    // 注释掉其余步骤
  ]
}
```

### 4. 强制使用特定计划文件

设置环境变量：
```bash
set FUSION_PLAN_PATH=D:/path/to/specific/fusion_manual_plan.json
```

---

## 常见问题

### Q1: "未找到 fusion_manual_plan.json"

**原因**：
- 没有生成计划文件
- 计划文件不在预期位置

**解决**：
1. 在 PC 端运行 `python tools/run_pipeline.py`
2. 确认生成了 `execution/runs/<run_id>/fusion_manual_plan.json`
3. 或设置环境变量 `FUSION_PLAN_PATH`

### Q2: "Profile xxx not found"

**原因**：
- `profile_id` 变量未正确解析
- Sketch 中没有封闭的 Profile

**解决**：
1. 检查 Sketch 是否创建了封闭轮廓
2. 检查变量引用是否正确（`${hub_profile_id}`）
3. 检查 `capture` 字段是否捕获了 `profile_id`

### Q3: "Component xxx not found"

**原因**：
- 组件未创建或创建失败
- `component_id` 变量未解析

**解决**：
1. 检查 `CREATE_COMPONENT` 步骤是否执行成功
2. 检查 `depends_on` 依赖关系是否正确
3. 检查变量捕获和引用

### Q4: 单位错误（模型太大或太小）

**原因**：
- 计划文件中使用了错误的单位
- 没有使用 `mm()` / `cm_vec()` 进行转换

**解决**：
1. 确认 JSON 计划中所有尺寸使用毫米（mm）
2. 检查 `modeling.py` 中的转换逻辑
3. 不要在 JSON 中手动除以 10

### Q5: 坐标系混淆（组件位置错误）

**原因**：
- 误将局部坐标当作世界坐标
- 父子组件关系理解错误

**解决**：
1. 理解 `transform.translation` 是**相对父组件**的局部坐标
2. 根组件下的子组件，`translation` 是世界坐标
3. 检查 `parent_component_id` 设置

---

## 性能优化

### 1. 批量操作

**避免**：
```json
// 为每个组件单独创建和激活
{"function": "CREATE_COMPONENT", "inputs": {"name": "arm_1"}},
{"function": "ACTIVATE_COMPONENT", "inputs": {"component_id": "arm_1"}},
{"function": "CREATE_COMPONENT", "inputs": {"name": "arm_2"}},
{"function": "ACTIVATE_COMPONENT", "inputs": {"component_id": "arm_2"}},
```

**推荐**：
```json
// 创建所有组件，然后批量激活
{"function": "CREATE_COMPONENT", "inputs": {"name": "arm_1"}},
{"function": "CREATE_COMPONENT", "inputs": {"name": "arm_2"}},
{"function": "CREATE_COMPONENT", "inputs": {"name": "arm_3"}},
{"function": "ACTIVATE_COMPONENT", "inputs": {"component_id": "arm_1"}},
```

### 2. 减少 Sketch 切换

在同一 Sketch 中完成所有图形绘制后再进行拉伸，减少 Sketch 创建和激活次数。

### 3. Profile 复用

如果多个特征使用相同的轮廓，可以复用同一个 `profile_id`（但需确保 Sketch 未被修改）。

---

## 扩展开发

### 1. 添加新的建模操作

**步骤**：

1. **在 `modeling.py` 中添加新方法**：
```python
def MY_NEW_OPERATION(self, component_id: str, param1: float, param2: str):
    """新操作的文档字符串
    
    参数单位：mm（如果有尺寸参数）
    """
    comp = self._components.get(component_id, self.root_comp)
    
    # 单位转换（如果需要）
    param1_cm = param1 / 10.0
    
    # Fusion API 调用
    # ...
    
    return {"result_key": "result_value"}
```

2. **更新 `functions/registry.py`**：
```python
"MY_NEW_OPERATION": FunctionSpec(
    name="MY_NEW_OPERATION",
    description="新操作的描述",
    inputs={
        "type": "object",
        "required": ["component_id", "param1"],
        "properties": {
            "component_id": {"type": "string"},
            "param1": {"type": "number"},
            "param2": {"type": "string"}
        }
    },
    outputs={
        "type": "object",
        "properties": {
            "result_key": {"type": "string"}
        }
    }
)
```

3. **在 JSON 计划中使用**：
```json
{
  "id": "my_step",
  "function": "MY_NEW_OPERATION",
  "inputs": {
    "component_id": "${component_id}",
    "param1": 100.0,
    "param2": "value"
  }
}
```

### 2. 修改变量解析逻辑

编辑 `orchestrator.py::_resolve_variables()` 函数，添加自定义解析规则。

### 3. 添加后处理步骤

编辑 `postprocess.py::run_all()` 函数，添加新的后处理调用。

---

## 架构演进

### 版本历史

**v1.0** - 初始版本
- 基础建模操作
- 简单变量替换
- 单文件实现

**v2.0** - 模块化重构
- 拆分为多个模块（orchestrator, modeling, plan_io, marker_io, postprocess）
- 状态标记文件系统
- 多级错误处理

**v2.1** - 单位系统统一
- 引入 `mm()`, `cm_vec()`, `cm_point()` 工具函数
- 消除所有临时单位判断
- 统一单位约定文档

**v2.2** - Profile 动态解析
- 不存储 Profile 对象引用
- 动态从 Sketch 查询 Profile
- 解决 Profile 失效问题

**v2.3** - 坐标系规范
- 明确局部坐标系语义
- `CREATE_COMPONENT` 的 `transform` 是相对父组件的局部变换
- 文档化坐标系约定

### 未来计划

- [ ] **参数化模型支持** - 支持 Fusion 360 参数和公式
- [ ] **Material 和 Appearance** - 自动设置材质和外观
- [ ] **Pattern 操作** - 圆周阵列、线性阵列、镜像
- [ ] **Fillet 和 Chamfer** - 倒角和圆角操作
- [ ] **更多 Sketch 图形** - 多边形、样条曲线、文本
- [ ] **Assembly Constraints** - 刚性约束、旋转约束、滑动约束
- [ ] **性能优化** - 批量操作、API 调用优化
- [ ] **交互式调试** - 可视化变量状态、断点调试

---

## 贡献指南

### 代码风格

- 遵循 PEP 8 Python 代码风格
- 使用类型提示（Type Hints）
- 编写完整的文档字符串（Docstrings）
- 单位转换通过工具函数完成，不在业务逻辑中硬编码

### 提交规范

```
feat: 添加新的建模操作 MY_NEW_OPERATION
fix: 修复 Profile 解析失败的问题
docs: 更新 README 文档
refactor: 重构变量解析逻辑
test: 添加单元测试
```

### 测试

在修改代码后，运行完整的测试流程：
1. 生成测试计划：`python tools/run_pipeline.py`
2. 在 Fusion 360 中运行脚本
3. 验证输出：检查模型与执行日志

---

## 许可证

本项目是 Fusion AI CAD System 的一部分，遵循项目整体许可证。

---

## 联系方式

如有问题或建议，请通过项目 Issue 系统反馈。

---

**最后更新**: 2026年2月2日
