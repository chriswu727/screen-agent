# Screen Agent — 面试项目讲解完整手册

## 一、30 秒 Elevator Pitch

> "I built an open-source MCP server called Screen Agent that gives AI agents the ability to see and interact with any desktop application. The core technical challenge was input reliability — existing tools like pyautogui fail for 20% of apps including game engines and Electron apps. I solved this with a multi-backend input chain using the Chain of Responsibility pattern: the system tries Accessibility API first, falls back to native CGEvent injection, then pyautogui as a last resort. Each backend implements the same Protocol, so adding new ones requires zero changes to the orchestrator. The system also has a real-time safety layer called Input Guardian — if the user touches their mouse or keyboard, all agent actions pause instantly. No other open-source tool in this space provides this level of safety."

---

## 二、项目概述

| 项目 | 细节 |
|------|------|
| **名称** | Screen Agent |
| **定位** | AI Agent 桌面自动化 MCP Server（macOS 专注） |
| **规模** | 3,128 行源码 + 1,360 行测试（122 个测试），20 个模块 |
| **协议** | MCP (Model Context Protocol) — 已被 OpenAI、Google、Microsoft 采纳的 AI 工具标准 |
| **工具数** | 19 个 MCP tools（截屏、点击、打字、OCR、安全控制等） |
| **CI** | GitHub Actions — 7 个 job（unit、integration、smoke、MCP protocol round-trip、lint、schema-check、import-check） |
| **GitHub** | github.com/chriswu727/screen-agent |

---

## 三、技术栈全览

### 语言与运行时
- **Python 3.10+**（使用 `from __future__ import annotations`、`|` union types、`slots=True` dataclasses）
- 异步优先：所有 I/O 用 `async/await`，CPU 密集用 `asyncio.to_thread()`
- macOS 专注：深度使用原生 API，不做半吊子跨平台

### 核心依赖
| 库 | 用途 | 为什么选它 |
|----|------|-----------|
| `mcp` | MCP 协议框架 | 行业标准，被 Anthropic/OpenAI/Google 支持 |
| `mss` | 截屏 | 轻量，比 pyautogui.screenshot() 快 |
| `pyautogui` | 输入兜底 | 生态成熟，作为 fallback |
| `Pillow` | 图像处理/编码 | 标准选择 |
| `pynput` | 用户输入监听 | Guardian 安全系统需要，支持后台监听 |
| `typer` | CLI 框架 | 类型安全，自动生成 help |

### macOS 原生依赖（推荐安装）
| 库 | 用途 |
|----|------|
| `pyobjc-framework-Quartz` | CGEvent 原生事件注入 + Retina 检测 |
| `pyobjc-framework-ApplicationServices` | Accessibility API (AXUIElement) |
| `pyobjc-framework-Vision` | Apple Vision Framework OCR |

### 开发工具
| 工具 | 用途 |
|------|------|
| `pytest` + `pytest-asyncio` | 122 个测试（78 unit + 44 integration） |
| `ruff` | Linting + 格式化 |
| `hatchling` | 构建系统 |
| GitHub Actions | 7-job CI pipeline |

---

## 四、架构设计（重点）

### 四层架构

```
┌──────────────────────────────────┐
│          MCP Layer               │  tool schemas + handler dispatch
│    tools.py │ handlers.py        │  (registry pattern, 不是 if/elif)
├──────────────────────────────────┤
│          Engine Layer            │  InputChain + Guardian + ScreenState
│  chain of responsibility │ safety│  (核心业务逻辑)
├──────────────────────────────────┤
│        Platform Layer            │  Protocols → Factory → 具体实现
│  InputBackend │ CaptureBackend   │  (依赖反转，面向接口编程)
│  WindowBackend│ OCRBackend       │
├──────────────────────────────────┤
│      macOS Backends              │  AX, CGEvent, Vision, AppleScript
└──────────────────────────────────┘
```

### 为什么这样分层

**面试回答**：
> "I chose this layered architecture for three reasons:
> 1. **Testability** — the Engine layer operates on Protocols, not concrete classes, so I can inject mock backends in unit tests without touching the OS. I have 44 integration tests that verify all 19 MCP handlers using mock backends.
> 2. **Extensibility** — adding Windows support means implementing 3 Protocols, not modifying existing code. This follows the Open/Closed Principle.
> 3. **Separation of concerns** — the MCP layer knows nothing about how clicks are delivered; the platform layer knows nothing about MCP. Each layer has exactly one reason to change."

### 为什么专注 macOS 而不是跨平台

**面试回答**：
> "I initially had Linux stubs but removed them. The reason: half-working cross-platform code is worse than well-tested single-platform code. macOS has unique APIs (Accessibility, CGEvent, Vision Framework) that require deep integration. Spreading effort across platforms would mean none of them work well. The architecture still supports adding platforms later — implementing the Protocols is all that's needed."

---

## 五、核心设计决策（面试高频问题）

### 1. Input Backend Chain — Chain of Responsibility

**问题**: pyautogui 对游戏引擎（Godot/Unity）和很多 Electron 应用无效。

**解决方案**: 三个 backend 按优先级自动降级。

```
AX (Accessibility API)          ← 语义级，最可靠
  ↓ 失败
CGEvent (Quartz 原生事件)        ← 原生注入，游戏也能用
  ↓ 失败
pyautogui (Python 跨平台)       ← 兜底
  ↓ 全部失败
InputDeliveryError (详细错误)    ← 包含每个 backend 的失败原因
```

**关键代码** (`engine/input_chain.py:_try_all()`):
```python
async def _try_all(self, action: str, **kwargs) -> ActionResult:
    attempts = []
    for backend in self._backends:
        try:
            method = getattr(backend, action)
            success = await method(**kwargs)
            if success:
                self._record(backend.name, action, success=True)
                return ActionResult(success=True, backend_used=backend.name, ...)
            attempts.append((backend.name, "returned False"))
        except Exception as e:
            attempts.append((backend.name, str(e)))
        self._record(backend.name, action, success=False)
    raise InputDeliveryError(action, attempts)
```

**面试亮点**:
- **Chain of Responsibility** 设计模式
- **遥测统计**：每个 backend 的 success/failure 计数和成功率，可观测性
- **线程安全**：InputChain 的统计用 `threading.Lock` 保护
- **Open/Closed**：添加新 backend 只需实现 `InputBackend` Protocol，不改 InputChain
- **错误透明**：`InputDeliveryError` 包含所有 backend 的失败详情

**面试 follow-up 问题与回答**:

> Q: "Why not just use the best backend?"
> A: "No single backend works for all apps. AX doesn't work for games (no accessibility tree). CGEvent requires macOS permissions. pyautogui uses deprecated APIs. The chain gives us the widest coverage with graceful degradation."

> Q: "How do you prevent performance issues from trying multiple backends?"
> A: "The first success short-circuits. In the common case (native app), AX succeeds immediately. The fallback path only executes when a backend explicitly fails, so there's no wasted work."

> Q: "How would you add a Windows backend?"
> A: "Implement the InputBackend Protocol with Win32 API calls (SendInput for CGEvent equivalent, UIAutomation for AX equivalent). Register it in the platform factory. Zero changes to InputChain or MCP layer."

---

### 2. Input Guardian — 实时安全系统

**问题**: AI agent 操控桌面有安全风险 — 可能在用户打字时点错地方，或操作不该碰的应用。

**解决方案**: 两个安全保证：

**保证 1: User Priority（用户优先）**
- pynput 后台线程监听所有键盘/鼠标事件
- 用户一碰输入设备 → agent 立即暂停
- 用户空闲 1.5 秒后 → agent 自动恢复
- `wait_for_clearance()` 是异步的，在等待时不阻塞其他操作

**保证 2: Scope Lock（作用域锁）**
- 应用白名单：agent 只能操作指定的应用（部分匹配，大小写无关）
- 区域约束：agent 只能在指定像素区域内操作（exclusive upper bound）
- 坐标检查在 clearance 中自动执行

**状态机**:
```
IDLE → (action requested) → ACTIVE
ACTIVE → (user input detected) → PAUSED
PAUSED → (user idle > cooldown) → ACTIVE
Any → (user locks) → LOCKED_OUT
LOCKED_OUT → (user unlocks) → IDLE
```

**线程安全细节**:
- Guardian 状态用 `threading.Lock` 保护
- pynput 回调在后台线程，`_record_user_input()` 加锁写时间戳
- `wait_for_clearance()` 在 async 事件循环中轮询，不阻塞
- Window backend 实例被缓存，避免每次 clearance 检查都重新创建

**面试亮点**:
- **竞品差异化**：没有任何开源竞品有这个功能
- **线程安全**：`threading.Lock` 保护所有共享状态
- **可配置**：cooldown、timeout、check_interval 全部可调
- **回调系统**：`on_pause()` / `on_resume()` 注册回调

---

### 3. Protocol-based 平台抽象

**4 个 Protocol**（`platform/protocols.py`）:

```python
@runtime_checkable
class InputBackend(Protocol):
    @property
    def name(self) -> str: ...
    def available(self) -> bool: ...
    async def click(self, point: Point, ...) -> bool: ...
    async def type_text(self, text: str) -> bool: ...
    async def press_key(self, key: str, modifiers: list[str] | None) -> bool: ...
    async def scroll(self, amount: int, point: Point | None) -> bool: ...
    async def move(self, point: Point) -> bool: ...
    async def drag(self, start: Point, end: Point, ...) -> bool: ...

class CaptureBackend(Protocol): ...
class WindowBackend(Protocol): ...
class OCRBackend(Protocol): ...
```

**为什么用 Protocol 而不是 ABC**:
> "Protocol supports structural subtyping — a class doesn't need to explicitly inherit from it, it just needs to implement the right methods. This is more Pythonic and allows third-party backends without modifying our code."

**工厂模式** (`platform/__init__.py`):
```python
def get_input_backends(config) -> list[InputBackend]:
    # 检测 OS → 如果不是 macOS 抛 PlatformNotSupportedError
    # 懒加载对应实现 → 按配置优先级排序
    # ImportError → 跳过该 backend
```

---

### 4. 替换 PaddleOCR → Apple Vision Framework

**问题**: PaddleOCR 是 2GB+ 的依赖，没人会为了 OCR 装它。

**解决方案**: 用 macOS 内置的 Vision Framework（通过 pyobjc 绑定）。

**技术细节**:
- 输入：PNG/JPEG 的 raw bytes
- 处理：`NSData` → `CGImageSource` → `CGImage` → `VNRecognizeTextRequest`
- 输出：文字 + confidence + bounding box（归一化坐标转像素坐标）
- 坐标系转换：Vision 用 bottom-left origin (0-1)，转为 top-left origin (像素)
- 多语言：en, zh-Hans, zh-Hant, ja, ko, de, fr, es

**面试回答**:
> "PaddleOCR is 2GB, requires CUDA, and is overkill for screen text recognition. Apple Vision Framework is already on every Mac, runs on the Neural Engine, and returns bounding boxes natively. The trade-off is it's macOS-only, but that's acceptable because our platform abstraction lets us plug in different OCR backends per OS."

---

### 5. Retina 坐标统一

**问题**: macOS Retina 显示器的逻辑分辨率 ≠ 物理像素。截屏用物理像素，点击用逻辑坐标，如果不统一就会偏移。

**解决方案**: `CoordinateSpace` 类统一管理。

```python
@dataclass(frozen=True)
class CoordinateSpace:
    scale_factor: float  # 2.0 for Retina
    screen_width: int    # logical
    screen_height: int   # logical

    def logical_to_physical(self, point: Point) -> Point: ...
    def physical_to_logical(self, point: Point) -> Point: ...
    def contains(self, point: Point) -> bool: ...  # exclusive upper bound
```

**规则**: 所有 MCP 工具参数和返回值用**逻辑坐标**。只有底层 backend（mss 截屏）需要物理像素，转换在 backend 内部完成。

**自动检测**: 用 `Quartz.CGDisplayPixelsWide()` / `CGDisplayModeGetWidth()` 算 scale factor，`@lru_cache` 缓存。fallback 到 mss 再到 1920x1080 默认值。

**边界约定**: `contains()` 和 `Region.contains()` 使用 exclusive upper bound（x+width 和 y+height 不在区域内），与 Python range() 和图形编程标准一致。

---

### 6. 错误体系

**8 个结构化异常**:
```
ScreenAgentError (base)
├── PlatformNotSupportedError    code: PLATFORM_NOT_SUPPORTED
├── PermissionDeniedError        code: PERMISSION_DENIED
├── ElementNotFoundError         code: ELEMENT_NOT_FOUND
├── GuardianBlockedError         code: GUARDIAN_BLOCKED
├── InputDeliveryError           code: INPUT_DELIVERY_FAILED
├── CoordinateOutOfBoundsError   code: COORDINATE_OUT_OF_BOUNDS
└── CaptureError                 code: CAPTURE_FAILED
```

每个异常有 `to_dict()` → JSON，LLM 客户端可程序化处理：
```json
{
  "error": {
    "code": "GUARDIAN_BLOCKED",
    "message": "Active window not in allowed apps",
    "details": {"allowed_apps": ["Chrome"], "active_app": "Slack"}
  }
}
```

**面试回答**:
> "String errors are fine for logs but useless for programmatic handling. Since our MCP client is an LLM, it needs machine-readable error codes to decide what to do — retry, ask the user, or give up. GUARDIAN_BLOCKED means 'switch to the right app', INPUT_DELIVERY_FAILED means 'try a different approach'."

---

### 7. MCP 层 — Handler Registry

**旧版**: 130 行 `if name == "click": ... elif name == "type_text": ...`

**新版**: 注册表模式

```python
_handlers: dict[str, HandlerFunc] = {}

def handler(name: str):
    def decorator(func):
        _handlers[name] = func
        return func
    return decorator

@handler("click")
async def handle_click(args: dict) -> ContentList:
    point = _parse_point(args)  # 输入验证 + 负坐标检查
    await _guardian_check(point)
    result = await ctx().input_chain.click(point, ...)
    return _text(asdict(result))
```

**输入验证**: `_parse_point()` 和 `_parse_region()` 统一校验坐标参数，非法值抛 `CoordinateOutOfBoundsError`。

**优势**: 添加新工具 = 写一个函数 + 加一个 `@handler` 装饰器。不碰任何现有代码。CI 中 `schema-check` job 自动验证所有 19 个 tool schema 都有对应 handler。

---

### 8. 集中配置 + 输入验证

**旧版**: 魔法数字散落在 10+ 个文件（0.3s、1.5s、2000px、80%...）

**新版**: 一个 `ScreenAgentConfig` dataclass + 环境变量覆盖 + 输入验证

```python
@dataclass
class ScreenAgentConfig:
    guardian: GuardianConfig   # cooldown, timeout, enabled
    capture: CaptureConfig     # max_dimension, jpeg_quality
    input: InputConfig         # backend_order, durations
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> ScreenAgentConfig:
        # 带验证的环境变量解析：
        # - 负数 cooldown → 警告并保留默认值
        # - 非法 backend 名 → 过滤掉，保留有效的
        # - max_dimension < 100 → 警告并保留默认值
```

---

## 六、设计模式汇总

| 模式 | 位置 | 目的 |
|------|------|------|
| **Chain of Responsibility** | `InputChain` | 多 backend 降级 |
| **Strategy / Protocol** | `protocols.py` | 可插拔平台后端 |
| **Observer** | `Guardian` (pynput) | 异步监听用户输入 |
| **State Machine** | `Guardian` (AgentState) | IDLE → ACTIVE → PAUSED ↔ LOCKED_OUT |
| **Factory** | `platform/__init__.py` | 按平台创建 backend |
| **Adapter** | `CoordinateSpace` | 逻辑/物理坐标转换 |
| **Registry** | `@handler` 装饰器 | MCP tool dispatch |
| **Dependency Injection** | `HandlerContext` | handler 不直接创建依赖 |
| **Value Object** | `Point`, `Region` (frozen) | 不可变数据 |
| **TTL Cache** | `ScreenState` | 屏幕状态缓存（线程安全） |

---

## 七、测试策略

### 当前覆盖（122 个测试）

| 模块 | 测试数 | 覆盖内容 |
|------|--------|----------|
| `test_types.py` | 12 | Point/Region/ActionResult 的创建、不可变性、exclusive upper bound 边界 |
| `test_errors.py` | 7 | 异常层级、error code 唯一性、to_dict() 序列化 |
| `test_config.py` | 16 | 默认值、环境变量覆盖、**无效输入验证**（负数、非法字符串、未知 backend） |
| `test_coords.py` | 6 | 坐标转换（1x、2x、分数缩放、round-trip、exclusive bounds） |
| `test_guardian.py` | 18 | ScopeLock、状态转换、clearance 逻辑、线程安全 |
| `test_input_chain.py` | 12 | 降级逻辑、异常处理、遥测、三级 fallback |
| `test_screen_state.py` | 7 | TTL 缓存、过期、线程安全 |
| **Unit 小计** | **78** | |
| `test_mcp_handlers.py` | **44** | 所有 19 个 handler 的 mock backend 测试 + 端到端 agent workflow |
| **总计** | **122** | |

### CI Pipeline（7 个 Job）

| Job | 运行环境 | 内容 |
|-----|---------|------|
| `unit-tests` | macOS × Python 3.10/3.12/3.13 | 78 个 unit tests |
| `integration-tests` | macOS | 44 个 handler 集成测试 |
| `mcp-smoke` | macOS | Server 启动、tool 注册、CLI 入口 |
| `mcp-protocol` | macOS | **真实 MCP JSON-RPC stdio 全流程**：initialize → list_tools → call tools → capture_screen |
| `lint` | Ubuntu | ruff check + format |
| `schema-check` | macOS | 验证 19 个 tool schema 都有对应 handler |
| `import-check` | macOS + Ubuntu | 跨平台 import 检查 |

### 测试设计亮点

**MockBackend**: 可配置的 mock 输入后端，支持 `fail=True` 和 `raise_error=True`，测试所有降级路径。

**MCP Protocol Round-Trip**: CI 中有一个 job 真正启动 MCP server 进程，通过 stdio 发送 JSON-RPC 消息（Content-Length framed），完成 initialize → list_tools → call tool 全流程。这验证了整个 MCP 协议栈的正确性。

**面试回答**:
> "I have two layers of tests. Unit tests mock the platform backends and test pure business logic — the input chain fallback, guardian safety rules, coordinate math, config validation. Integration tests mock at the backend level but exercise the full MCP handler dispatch pipeline, verifying that tool schemas match handlers, arguments are parsed correctly, and error responses are properly structured. On CI, there's also an end-to-end MCP protocol test that starts the actual server process and talks to it over stdio with JSON-RPC."

---

## 八、竞品对比

| 特性 | Screen Agent | Zavora (Rust) | Windows-MCP | Desktop Pilot |
|------|-------------|---------------|-------------|---------------|
| 语言 | Python | Rust NAPI | Python | Swift/Python |
| 平台 | macOS（深度） | macOS only | Windows only | macOS only |
| 输入方式 | 3 backend 降级链 | CGEvent only | Win32 API | AX + AppleScript |
| 安全系统 | Guardian ✅ | ❌ | ❌ | ❌ |
| OCR | Apple Vision (0 依赖) | ❌ | RapidOCR | ❌ |
| 坐标统一 | Retina-aware ✅ | ❌ | N/A | ❌ |
| 测试 | 122 tests + 7-job CI | Unknown | Unknown | Unknown |
| 遥测 | per-backend stats ✅ | ❌ | ❌ | ❌ |
| 输入验证 | coord/config 验证 ✅ | Unknown | Unknown | Unknown |

**核心差异化**:
1. 唯一有 **Input Guardian** 安全系统的
2. 唯一有 **多 backend 降级链 + 遥测** 的
3. 唯一有 **MCP protocol round-trip CI 测试** 的

---

## 九、系统设计面试可能问到的问题

### Q: "How would you scale this to support multiple simultaneous agents?"
> A: "Currently the Guardian is a singleton per server process. For multi-agent, I'd make Guardian instances per-agent with separate scope locks, and add a coordination layer that prevents two agents from clicking the same region simultaneously — essentially a distributed lock on screen regions."

### Q: "What happens if the user moves the mouse while an agent drag operation is in progress?"
> A: "The Guardian detects user input between drag steps because pynput runs on a separate thread. The drag would be interrupted mid-path. The CGEvent drag implementation uses configurable step duration from the config, and I could improve this by checking clearance at each interpolation step."

### Q: "How would you handle multi-monitor setups?"
> A: "Currently we capture the primary display only (mss.monitors[1]). For multi-monitor, I'd extend CoordinateSpace to track per-monitor offsets and scale factors, and add a monitor parameter to capture and click tools."

### Q: "Why Python instead of Rust/Swift for performance?"
> A: "The bottleneck isn't CPU — it's OS API calls (screen capture, event injection). Those take 10-50ms regardless of language. Python gives us faster development, the MCP Python SDK, and the pyobjc bridge to call native macOS C APIs directly. For the CGEvent backend, Python just calls the same Quartz C functions that a Swift app would."

### Q: "How do you test the safety guarantees?"
> A: "Unit tests cover the logic: scope checking, state transitions, clearance results with both inclusive and exclusive bounds. Integration tests verify that guardian blocking produces the correct structured error response via MCP. For the real-time user-priority guarantee, I'd need integration tests with simulated input events via pynput's Controller class. The key invariant: if user input timestamp < cooldown, wait_for_clearance() must not return allowed=True."

### Q: "What would a production deployment look like?"
> A: "Screen Agent is designed for local use (runs on the developer's machine). For enterprise deployment, I'd add: (1) audit logging of all actions, (2) remote kill switch via a webhook, (3) rate limiting per tool, (4) encrypted config for sensitive settings, and (5) a web dashboard showing backend stats and action history."

### Q: "Why did you drop Linux support?"
> A: "I had Linux stubs initially but removed them. Half-working cross-platform code is worse than well-tested single-platform code. macOS has unique APIs (Accessibility, CGEvent, Vision Framework) that need deep integration. The Protocol-based architecture means adding Linux back is just implementing 3 interfaces — no existing code changes needed."

### Q: "How do you handle invalid input from the LLM?"
> A: "All handler inputs go through validation helpers: `_parse_point()` rejects negative coordinates, `_parse_region()` validates all 4 fields, and the config loader validates env vars (negative cooldown, unknown backend names, too-small dimensions). Invalid input returns structured errors with specific error codes, not generic 500s."

---

## 十、项目与目标公司的技术匹配

| 公司 | 相关团队 | 我的项目怎么 match |
|------|---------|-------------------|
| **Google** | Gemini / AI Agent | MCP 是 Google 已采纳的标准；Vision AI 方向；Protocol round-trip 测试 |
| **Amazon** | AWS AI / Bedrock | 可配置性 + 输入验证、Production 思维、7-job CI pipeline |
| **Meta** | AI Infrastructure | 开源项目、Protocol 抽象、122 个测试覆盖 |
| **Apple** | macOS / Accessibility | 深度使用 AX API、Vision Framework、Quartz、CGEvent — 全 Apple 原生技术栈 |
| **Microsoft** | Copilot / Azure AI | MCP (MS 已支持)、安全设计 (Guardian)、结构化错误处理 |
| **Databricks** | ML Platform | 系统设计、可观测性（per-backend 遥测统计） |
| **Shopify** | Applied ML / GenAI | DX（开发者体验）、简单安装、清晰文档 |

---

## 十一、关键数字速记

- **3,128** 行源码，**1,360** 行测试
- **4** 层架构（MCP → Engine → Platform → macOS Backends）
- **3** 个输入后端（AX → CGEvent → pyautogui）
- **19** 个 MCP 工具
- **8** 个结构化异常类型
- **122** 个测试（78 unit + 44 integration）
- **7** 个 CI job（含 MCP protocol round-trip）
- **10** 个设计模式
- PaddleOCR **2GB** → Apple Vision **0** 额外依赖
- 环境变量 **5** 个可配置参数，全部带输入验证
