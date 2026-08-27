"""FastAPI 后端主程序 - Web 版录制回放工具"""
from __future__ import annotations
import asyncio
import json
import os
import shutil
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# 添加项目根目录到路径
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from recorder.agent import DeviceInterface, ActionVerifier
from recorder.collectors.android_uia import AndroidUiaCollector
from recorder.air_assembler import ScriptAssembler
from recorder.codegen.uia2_codegen import Uia2Codegen
from recorder.bus import EventBus

# 配置
BASE_DIR = ROOT
FRONTEND_DIR = BASE_DIR / "frontend"
OUTPUT_DIR = BASE_DIR / "out"
SESSIONS_DIR = OUTPUT_DIR / "sessions"

# 会话清理配置
SESSION_RETENTION_DAYS = 7  # 自动清理超过7天的会话
MAX_SESSIONS = 50  # 最多保留的会话数量

# 确保目录存在
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Reau 自动化测试工具", version="2.0")

# 全局状态
device: Optional[DeviceInterface] = None
collector: Optional[AndroidUiaCollector] = None
is_recording = False
is_playing = False
playback_thread: Optional[threading.Thread] = None
current_session_dir: Optional[str] = None
ws_clients: list[WebSocket] = []


# ============ 数据模型 ============

class ConnectRequest(BaseModel):
    serial: str = ""

class PlaybackRequest(BaseModel):
    session_id: str = ""
    speed: float = 1.0
    loop_count: int = 1

class ExecuteActionRequest(BaseModel):
    action_type: str = "click"
    target: dict = {}
    params: dict = {}

class AiTaskRequest(BaseModel):
    task: str
    max_steps: int = 20


# ============ 工具函数 ============

async def broadcast_log(message: str, level: str = "info"):
    """广播日志消息给所有 WebSocket 客户端"""
    data = json.dumps({
        "type": "log",
        "level": level,
        "message": message,
        "timestamp": time.time()
    })
    disconnected = []
    for ws in ws_clients:
        try:
            await ws.send_text(data)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        if ws in ws_clients:
            ws_clients.remove(ws)


def log_callback(message: str, level: str = "info"):
    """日志回调 - 用于线程中调用"""
    # 直接打印日志
    time_str = time.strftime("%H:%M:%S")
    prefix = {"info": "ℹ️", "success": "✅", "error": "❌", "warning": "⚠️"}.get(level, "ℹ️")
    print(f"[{time_str}] {prefix} {message}")
    
    # 尝试通过事件循环广播（如果存在）
    try:
        loop = asyncio.get_running_loop()
        if loop.is_running():
            asyncio.ensure_future(broadcast_log(message, level))
    except RuntimeError:
        # 没有正在运行的事件循环，保存日志待后续发送
        pass
    except Exception:
        pass


def get_available_sessions() -> list:
    """获取可用的会话列表"""
    sessions = []
    if SESSIONS_DIR.exists():
        for d in sorted(SESSIONS_DIR.iterdir(), reverse=True):
            if d.is_dir():
                script_path = d / "script.py"
                if script_path.exists():
                    sessions.append({
                        "id": d.name,
                        "name": d.name.replace("_", " "),
                        "path": str(d),
                        "has_script": True,
                        "template_count": len(list((d / "templates").glob("*.png"))) if (d / "templates").exists() else 0,
                    })
    return sessions


def create_session_dir() -> str:
    """创建新的会话目录"""
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    session_dir = SESSIONS_DIR / timestamp
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "templates").mkdir(exist_ok=True)
    (session_dir / "screenshots").mkdir(exist_ok=True)
    return str(session_dir)


def cleanup_old_sessions(retention_days: int = None, max_sessions: int = None) -> dict:
    """清理旧会话
    
    Args:
        retention_days: 保留天数，超过此天数的会话将被删除
        max_sessions: 最多保留的会话数量，超出的最旧会话将被删除
    
    Returns:
        清理结果统计
    """
    if retention_days is None:
        retention_days = SESSION_RETENTION_DAYS
    if max_sessions is None:
        max_sessions = MAX_SESSIONS

    cleaned_by_age = 0
    cleaned_by_count = 0
    freed_bytes = 0

    if not SESSIONS_DIR.exists():
        return {"cleaned_by_age": 0, "cleaned_by_count": 0, "freed_bytes": 0}

    sessions = []
    for d in SESSIONS_DIR.iterdir():
        if d.is_dir():
            mtime = datetime.fromtimestamp(d.stat().st_mtime)
            size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
            sessions.append({"path": d, "mtime": mtime, "size": size})

    # 按修改时间排序（最新的在前）
    sessions.sort(key=lambda s: s["mtime"], reverse=True)

    # 1. 按天数清理
    cutoff_date = datetime.now() - timedelta(days=retention_days)
    for s in sessions:
        if s["mtime"] < cutoff_date:
            try:
                shutil.rmtree(s["path"])
                cleaned_by_age += 1
                freed_bytes += s["size"]
            except Exception:
                pass

    # 2. 按数量清理（重新获取列表）
    remaining = []
    for d in SESSIONS_DIR.iterdir():
        if d.is_dir():
            mtime = datetime.fromtimestamp(d.stat().st_mtime)
            size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
            remaining.append({"path": d, "mtime": mtime, "size": size})

    remaining.sort(key=lambda s: s["mtime"], reverse=True)

    if len(remaining) > max_sessions:
        for s in remaining[max_sessions:]:
            try:
                shutil.rmtree(s["path"])
                cleaned_by_count += 1
                freed_bytes += s["size"]
            except Exception:
                pass

    return {
        "cleaned_by_age": cleaned_by_age,
        "cleaned_by_count": cleaned_by_count,
        "freed_bytes": freed_bytes,
        "freed_mb": round(freed_bytes / (1024 * 1024), 2),
    }


# ============ WebSocket ============

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.append(ws)
    await broadcast_log("客户端已连接", "success")
    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        if ws in ws_clients:
            ws_clients.remove(ws)


# ============ 设备管理 API ============

@app.get("/api/device/status")
async def get_device_status():
    """获取设备状态"""
    global device
    if device and device.is_connected:
        state = device.get_state(include_screenshot=False)
        return {
            "connected": True,
            "serial": device.serial,
            "resolution": f"{state.device_width}x{state.device_height}",
        }
    return {"connected": False}


@app.post("/api/device/connect")
async def connect_device(req: ConnectRequest):
    """连接设备"""
    global device
    log_callback(f"正在连接设备: {req.serial or '默认'}")
    device = DeviceInterface(serial=req.serial)
    success = device.connect()
    if success:
        log_callback(f"设备连接成功", "success")
        return {"success": True, "serial": device.serial}
    else:
        log_callback("设备连接失败", "error")
        return {"success": False, "message": "连接失败"}


@app.post("/api/device/disconnect")
async def disconnect_device():
    """断开设备"""
    global device
    if device:
        device.disconnect()
        log_callback("设备已断开", "warning")
    return {"success": True}


@app.get("/api/device/screenshot")
async def take_screenshot():
    """获取屏幕截图"""
    global device
    if not device or not device.is_connected:
        return {"error": "设备未连接"}
    state = device.get_state(include_screenshot=True, include_ui=False)
    if state.screenshot:
        import base64
        b64 = base64.b64encode(state.screenshot).decode()
        return {"screenshot": b64}
    return {"error": "截图失败"}


@app.get("/api/device/ui-elements")
async def get_ui_elements():
    """获取 UI 元素"""
    global device
    if not device or not device.is_connected:
        return {"error": "设备未连接"}
    state = device.get_state(include_screenshot=False, include_ui=True)
    elements = [
        {"text": e.text, "resource_id": e.resource_id, "bounds": e.bounds}
        for e in state.ui_elements
    ]
    return {"elements": elements, "count": len(elements)}


# ============ 录制 API ============

@app.post("/api/recording/start")
async def start_recording():
    """开始录制"""
    global is_recording, collector, current_session_dir
    if is_recording:
        return {"error": "已经在录制中"}
    
    if not device or not device.is_connected:
        return {"error": "请先连接设备"}
    
    current_session_dir = create_session_dir()
    is_recording = True
    
    bus = EventBus()
    collector = AndroidUiaCollector(
        device=device._d,
        bus=bus,
        adb_path="",
        output_dir=current_session_dir,
        session_dir=current_session_dir,
    )
    
    # 设置日志回调
    original_emit = collector.emit
    def emit_with_log(action):
        original_emit(action)
        log_callback(f"录制事件: {action.type} {action.target}", "info")
    collector.emit = emit_with_log
    
    collector.start()
    log_callback("开始录制...", "success")
    
    return {"success": True, "session_dir": current_session_dir}


@app.post("/api/recording/stop")
async def stop_recording():
    """停止录制"""
    global is_recording, collector, current_session_dir
    if not is_recording:
        return {"error": "没有在录制"}
    
    is_recording = False
    actions = collector.stop()
    log_callback(f"录制完成，共 {len(actions)} 个操作", "success")
    
    # 生成脚本
    if actions and current_session_dir:
        codegen = Uia2Codegen()
        assembler = AirAssembler()
        script_path = os.path.join(current_session_dir, "script.py")
        codegen.emit_to_script(actions, script_path)
        log_callback(f"脚本已生成: {script_path}", "success")
        
        return {
            "success": True,
            "action_count": len(actions),
            "script_path": script_path,
        }
    
    return {"success": False, "message": "没有录制到操作"}


# ============ 回放 API ============

@app.get("/api/playback/sessions")
async def list_sessions():
    """获取会话列表"""
    sessions = get_available_sessions()
    return {"sessions": sessions}


@app.post("/api/playback/start")
async def start_playback(req: PlaybackRequest):
    """开始回放"""
    global is_playing, playback_thread, device
    if is_playing:
        return {"error": "正在回放中"}
    
    if not device or not device.is_connected:
        return {"error": "请先连接设备"}
    
    sessions = get_available_sessions()
    session = next((s for s in sessions if s["id"] == req.session_id), None)
    if not session:
        return {"error": f"会话不存在: {req.session_id}"}
    
    script_path = os.path.join(session["path"], "script.py")
    if not os.path.exists(script_path):
        return {"error": "脚本文件不存在"}
    
    is_playing = True
    
    def run_playback():
        try:
            log_callback(f"开始回放: {req.session_id}", "info")
            
            with open(script_path, "r", encoding="utf-8") as f:
                code = f.read()
            
            # 清理代码
            import re
            clean_lines = []
            skip_next = False
            for line in code.split('\n'):
                if 'def check_stop' in line:
                    skip_next = True
                    continue
                if skip_next and ('pass' in line or 'return' in line):
                    skip_next = False
                    continue
                clean_lines.append(line)
            clean_code = '\n'.join(clean_lines)
            
            # 执行脚本
            for loop_idx in range(req.loop_count):
                if loop_idx > 0:
                    log_callback(f"循环 {loop_idx + 1}/{req.loop_count}", "info")
                
                namespace = {
                    "d": device._d,
                    "time": __import__("time"),
                    "_time": __import__("time"),
                    "cv2": __import__("cv2"),
                    "np": __import__("numpy"),
                    "print": lambda *args, **kwargs: log_callback(" ".join(map(str, args))),
                    "_sleep": lambda s: time.sleep(s),
                    "check_stop": lambda: None,
                }
                namespace.update({"__builtins__": __builtins__})
                
                local_ns = namespace.copy()
                exec(clean_code, namespace, local_ns)
                
                if "run" in local_ns:
                    local_ns["run"]()
            
            log_callback("回放完成", "success")
        except Exception as e:
            log_callback(f"回放异常: {e}", "error")
        finally:
            global is_playing
            is_playing = False
    
    playback_thread = threading.Thread(target=run_playback, daemon=True)
    playback_thread.start()
    
    return {"success": True}


@app.post("/api/playback/stop")
async def stop_playback():
    """停止回放"""
    global is_playing
    is_playing = False
    log_callback("已发送停止指令", "warning")
    return {"success": True}


# ============ AI Agent API ============

@app.post("/api/ai/execute")
async def ai_execute_task(req: AiTaskRequest):
    """AI 执行任务 - 使用 LLM Agent"""
    global device
    if not device or not device.is_connected:
        return {"error": "请先连接设备"}
    
    log_callback(f"AI 开始执行任务: {req.task}", "info")
    
    # 创建 LLM 客户端
    from recorder.agent import create_llm_client, AIAgent
    
    llm_client = create_llm_client("taishi")
    
    if llm_client:
        # 使用真正的 AI Agent
        log_callback("使用 LLM Agent 执行任务", "info")
        agent = AIAgent(llm_client, device)
        
        # 在后台线程中执行（避免阻塞）
        result_container = {}
        
        def run_agent():
            try:
                result = agent.execute_task(req.task, req.max_steps)
                result_container["result"] = result
            except Exception as e:
                result_container["error"] = str(e)
                log_callback(f"AI Agent 异常: {e}", "error")
        
        thread = threading.Thread(target=run_agent, daemon=True)
        thread.start()
        thread.join(timeout=req.max_steps * 10)  # 超时保护
        
        if "error" in result_container:
            return {"error": result_container["error"]}
        
        result = result_container.get("result", {})
        log_callback(f"AI 任务完成，共执行 {result.get('steps', 0)} 步", "success")
        
        # 格式化结果
        results = []
        for item in result.get("results", []):
            results.append({
                "step": len(results) + 1,
                "action": item,
                "success": "✅" in item,
            })
        
        return {
            "success": True,
            "steps": result.get("steps", 0),
            "completed": result.get("completed", False),
            "results": results,
            "task": req.task,
            "mode": "llm",  # 标记使用了 LLM
        }
    else:
        # 后备：使用规则匹配
        log_callback("LLM 不可用，使用规则匹配模式", "warning")
        
        task_completed = False
        steps_taken = 0
        results = []
        
        while not task_completed and steps_taken < req.max_steps:
            steps_taken += 1
            
            state = device.get_state()
            log_callback(f"步骤 {steps_taken}: 当前屏幕有 {len(state.ui_elements)} 个元素 (规则模式)", "info")
            
            target_texts = ["确定", "开始", "领取", "战斗", "进入", "确认", "知道了", "关闭"]
            action_taken = False
            
            for text in target_texts:
                elem = state.get_element_by_text(text)
                if elem:
                    x1, y1, x2, y2 = elem.bounds
                    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                    result = device.execute(DeviceAction.click_by_coord(cx, cy))
                    
                    log_callback(f"点击 '{text}': {'成功' if result.success else '失败'}", "success" if result.success else "error")
                    results.append({
                        "step": steps_taken,
                        "action": f"点击 '{text}'",
                        "success": result.success,
                    })
                    
                    import time as _time
                    _time.sleep(0.5)
                    action_taken = True
                    break
            
            if not action_taken:
                log_callback("没有找到可执行的操作，任务可能已完成", "info")
                task_completed = True
        
        return {
            "success": True,
            "steps": steps_taken,
            "results": results,
            "task": req.task,
            "mode": "rule",  # 标记使用了规则匹配
        }


@app.post("/api/ai/test-connection")
async def test_llm_connection():
    """测试 LLM 连接"""
    from recorder.agent import create_llm_client
    
    llm_client = create_llm_client("taishi")
    
    if not llm_client:
        return {"success": False, "message": "太石 LLM 未配置或未启用"}
    
    try:
        # 发送一个简单的测试请求
        response = llm_client.chat(
            messages=[{"role": "user", "content": "你好，请回复'连接成功'"}],
            system_prompt="你是一个测试助手"
        )
        
        if response:
            return {
                "success": True,
                "message": "连接成功",
                "response": response[:100],
            }
        else:
            return {"success": False, "message": "LLM 未返回响应"}
    except Exception as e:
        return {"success": False, "message": f"连接失败: {str(e)}"}


@app.get("/api/ai/config")
async def get_ai_config():
    """获取 AI 配置状态"""
    try:
        from config.llm_config import TAISHI_LLM
        return {
            "enabled": TAISHI_LLM.get("enabled", False),
            "name": TAISHI_LLM.get("name", ""),
            "api_base_configured": bool(TAISHI_LLM.get("api_base", "")),
            "api_key_configured": bool(TAISHI_LLM.get("api_key", "")),
            "model": TAISHI_LLM.get("model", ""),
            "supports_vision": TAISHI_LLM.get("supports_vision", False),
        }
    except Exception as e:
        return {"error": str(e)}


# ============ 清理 API ============

@app.post("/api/sessions/cleanup")
async def do_cleanup(retention_days: int = 7, max_sessions: int = 50):
    """清理旧会话"""
    result = cleanup_old_sessions(retention_days, max_sessions)
    log_callback(f"清理完成: 删除过期 {result['cleaned_by_age']} 个, 超限 {result['cleaned_by_count']} 个, 释放 {result['freed_mb']} MB", "success")
    return result


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除指定会话"""
    session_path = SESSIONS_DIR / session_id
    if not session_path.exists():
        return {"error": "会话不存在"}
    try:
        shutil.rmtree(session_path)
        log_callback(f"会话已删除: {session_id}", "success")
        return {"success": True}
    except Exception as e:
        return {"error": str(e)}


# ============ 状态 API ============

@app.get("/api/status")
async def get_status():
    """获取系统状态"""
    return {
        "device_connected": device.is_connected if device else False,
        "recording": is_recording,
        "playing": is_playing,
        "sessions": len(get_available_sessions()),
    }


# ============ 前端静态文件 ============

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
    
    @app.get("/")
    async def index():
        return FileResponse(str(FRONTEND_DIR / "index.html"))


# ============ 启动事件 ============

@app.on_event("startup")
async def startup_event():
    log_callback("服务启动: http://localhost:8000", "success")
    
    # 启动时自动清理旧会话
    result = cleanup_old_sessions()
    if result["cleaned_by_age"] > 0 or result["cleaned_by_count"] > 0:
        log_callback(f"自动清理: 删除过期 {result['cleaned_by_age']} 个, 超限 {result['cleaned_by_count']} 个, 释放 {result['freed_mb']} MB", "info")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
