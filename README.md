# Agent 职责（按当前代码实现）

## Agent1：需求转知识图谱

- 抽取组件 `components`
  - 识别系统需要哪些组件，给出形状类型与语义级尺寸，例如直径、厚度、长度、宽度等。
  - 这里的尺寸是语义尺寸，不直接输出 CAD 世界坐标或最终建模参数。
- 抽取标准件候选 `standard_parts`
  - 尽量把连接件或标准件定位到可识别的标准型号，例如 `M5x12`、`DIN`、`GB`、`ISO`。
  - 这一阶段内部包含标准件 grounding 子过程：先产出 designation、类别、候选依据与绑定对象，再在 `part_library` 中完成库绑定与尺寸落地。
- 抽取连接需求 `connection_requirements`
  - 把“谁和谁连接、连接目的、自然语言描述、约束意图”结构化出来。
  - 不只写“固定住/装上去”，还会尽量落到 `fastening_mechanism`、`structural_fixation`、`torque_transfer` 等语义类型。
  - 对涉及紧固或夹紧的连接，补全并校验 `connection_decision`，供 Agent2 推断孔型、紧固方式和派生几何修改。
- 复杂组件自动拆解
  - 例如用户说“轮子”，Agent1 会拆成 `rim`、`tire`、`hub`、`axle` 等子组件，并分别定义。
  - 父组件在当前实现中通常会保留，但只作为结构节点或容器节点，不再作为单独的建模实体，避免重复与冲突。
  - 拆解后会补齐 `component_hierarchy`、`parent_id`、`position_parent` 等结构信息，保证下游可继续推理。
- 硬约束
  - KG 不再使用旧的 `relations[]`，当前契约以 `connection_requirements[]` 为准。

输入（实际文件）

- `input/anforderungsliste.yaml`

输出（实际文件）

- `knowledge/knowledge_graph.json`
  - `components`
  - `standard_parts`
  - `connection_requirements`
  - `component_hierarchy`

### Agent1 子过程：标准件 grounding

- 读取 Agent1 产出的 `standard_parts`
- 在 `part_library` 与索引中做绑定
- 有精确匹配就精确绑定；没有完全匹配时按类别、标准、尺寸做最近匹配；无法绑定的进入 unresolved 列表

输出（实际文件）

- `planning/standard_parts_resolved.json`
- `planning/standard_parts_unresolved.json`

## Agent2：知识图谱转几何语义与装配语义

- 推断连接导致的改动 `derived_changes`
  - 例如两块板用螺丝固定，会推断孔、沉孔、沉头、螺纹孔、配合孔、安装面、加强区等派生几何修改。
- 推断连接落点与阵列语义 `connection_placements`
  - 推断孔位或落点分布原则，例如避免穿模、不靠边、考虑常见受力、均匀分布等。
  - 输出的是阵列语义和局部参考，不是每个孔的世界坐标点。
- 输出 pattern 参数而不是直接坐标
  - 例如矩形阵列、圆周阵列，包含 `count`、`pattern_radius`、`edge_margin`、间距等参数。
  - pattern 的实例展开与初始位置求解交给 Agent3a。
- 声明接口 `interface_declarations`
  - 为每个组件声明可用于装配、连接、定位的语义接口。
  - 这些接口是后续建模和装配绑定的桥梁，不是执行层最终面 ID。
- 生成装配契约
  - 把连接语义转成装配相关的几何契约，供 Agent4 做装配编译。
- 硬约束
  - 不输出世界坐标，位置表达必须以组件局部参考系和接口语义为主。
  - 不允许修改 Agent1 冻结下来的核心事实，例如组件基础尺寸和 `connection_decision`。

输入（实际文件）

- `knowledge/knowledge_graph.json`
- `planning/standard_parts_resolved.json`
- `planning/standard_parts_unresolved.json`

输出（实际文件）

- `planning/geometry_semantics_modeling_round_1.json`
- `planning/geometry_semantics_assembly_round_1.json`
- `planning/errors/geometry_semantics_feasibility.json`

## Agent3a：几何语义落地与实例化

- 计算组件初始位置 `initial_placements`
  - 负责全局布局和组件初始摆放，为后续执行层注入确定性 transform。
- 计算特征实例与定位语义
  - 把 Agent2 给出的 pattern 语义展开成可落地的实例、偏置、局部参考信息。
- 决定建模策略 `modeling_strategy`
  - 例如采用 `extrude`、`revolve` 等可执行层支持的建模范式。
  - 这里做的是“怎么表达成可编译的建模策略”，不是直接输出执行层 API 步骤。
- 继承接口语义
  - 把后续特征编译需要的接口清单随 `shape_realization` 一并带下去。
- 强约束
  - 必须符合执行层已有能力，不允许凭空发明执行层不存在的动作。
  - 标准件库绑定和插入不在 Agent3a 完成。

输入（实际文件）

- `planning/geometry_semantics_modeling_round_1.json`
- `knowledge/knowledge_graph.json`

输出（实际文件）

- `planning/shape_realization_round_1.json`
- `placement_diagnostics.json`

## Agent3b：形状实现编译为几何计划

- 对齐功能注册表
  - 只使用执行层支持的函数集合。
- 把 `shape_realization` 编译成几何建模 plan
  - 决定 function 与 API 调用顺序，例如先创建组件、再草图、再特征、再阵列。
  - 每一步都包含输入参数、依赖关系、输出捕获，供后续步骤引用。
- 编译特征补丁
  - 将孔、沉孔、沉头、螺纹等 anchored feature 语义编译成具体函数步骤。
- 注入标准件步骤
  - 根据 `standard_parts_resolved.json` 把标准件插入、校验、替换相关步骤编译进几何计划。
- 生成接口清单
  - 输出供 Agent4 和 Agent5 使用的 `interface_manifest`，用于后续装配绑定与接口闭包检查。

输入（实际文件）

- `planning/shape_realization_round_1.json`
- `planning/standard_parts_resolved.json`
- `planning/geometry_semantics_modeling_round_1.json`
- `planning/geometry_semantics_assembly_round_1.json`

输出（实际文件）

- `planning/geometry_plan_round_1.json`
- `planning/interface_manifest_round_1.json`

## Agent4：装配语义编译

- 提取装配需求
  - 判断哪些组件需要装配、装配目的是什么。
- 推算装配位置与约束
  - 例如哪两个面贴合、哪条轴对齐哪个孔中心、哪些自由度保留或限制。
- 生成装配语义
  - 将自由度、对齐方式、约束意图表达完整。
- 编译装配 patch 或装配步骤
  - 输出装配函数调用顺序，并记录 unresolved 或 dropped relation 等诊断信息。

输入（实际文件）

- `knowledge/knowledge_graph.json`
- `planning/geometry_semantics_assembly_round_1.json`
- `planning/geometry_semantics_modeling_round_1.json`
- `planning/geometry_plan_round_1.json`
- `planning/interface_manifest_round_1.json`

输出（实际文件）

- `planning/assembly_semantics_round_1.json`
- `planning/assembly_patch_round_1.json`

## Agent5：总计划拼接、链接与质量闸门

- 合并几何阶段与装配阶段
  - 把 `geometry_plan` 与 `assembly_patch` 统一成一套 `steps` 流。
- 注入初始 placement
  - 读取 Agent3a 的 `initial_placements`，把确定性 transform 步骤注入最终计划。
- 依赖排序与链接
  - 处理 `depends_on`、变量引用、实例合并、对称折叠、拓扑排序和循环检查。
- 做质量闸门
  - 读取 feasibility 结果，必要时阻断 compose。
  - 做接口闭包检查，保证前后阶段引用一致。
- 边界
  - Agent5 不再重复插入标准件；标准件插入已经在 Agent3b 完成。
  - 运行结束后的 `memory/run_memory.json` 属于 Agent5 的观测/导出子过程，不单独计为新 Agent。

输入（实际文件）

- `planning/geometry_plan_round_1.json`
- `planning/assembly_patch_round_1.json`
- `planning/interface_manifest_round_1.json`
- `planning/shape_realization_round_1.json`
- `planning/geometry_semantics_modeling_round_1.json`
- `planning/errors/geometry_semantics_feasibility.json`

输出（实际文件）

- `planning/function_plan_round_1.json`
- `planning/function_plan.json`

## 执行层补充说明

- `fusion_manual_plan.json` 不是 Agent5 直接输出的文件。
- 当前实现中，Agent5 先产出 `planning/function_plan.json`，然后由流水线在 `tools/run_pipeline.py` 中导出 `fusion_manual_plan.json`，供 `fusion_api_server` 读取执行。
