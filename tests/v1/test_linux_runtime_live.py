"""Linux SSH + 单版本 OpenCode 真实验证；独立配置/数据/仓库，不操作旧服务。"""

import asyncio
import hashlib
import json
import os
import shlex
import time
from pathlib import Path
from uuid import uuid4

import pytest

from domains.runtime import NativeSessionBinding, OpenCodeClient, OpenCodeConfig, RuntimePurpose
from domains.runtime.evidence import evidence_index, final_message, native_tree, usage_facts
from domains.runtime.execution_config import protected_json
from domains.runtime.ssh import SSHSession

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(os.getenv("ASTRA_LIVE_LINUX") != "1", reason="真实 Linux SSH 验证需显式启用"),
]
TESTS = """const assert = require('node:assert/strict');
const {add} = require('./arithmetic.cjs');
assert.equal(add(2,3),5);
assert.equal(add(-7,2),-5);
assert.equal(add(0,0),0);
assert.equal(add(10000000000,10000000000),20000000000);
assert.throws(()=>add('2',1),TypeError);
console.log('5 original assertions passed');
"""


async def test_linux_119_native_execution_tunnel_reconnect_and_evidence():
    credentials = protected_json(os.environ["ASTRA_LIVE_LINUX_SSH_FILE"])
    ssh = SSHSession(
        host=credentials["host"],
        port=credentials["port"],
        username=credentials["username"],
        password=credentials["password"],
        known_hosts=os.environ["ASTRA_LIVE_LINUX_KNOWN_HOSTS"],
    )
    root = os.environ["ASTRA_LIVE_LINUX_ROOT"].rstrip("/") + "/" + uuid4().hex
    assert root.startswith("/") and ".." not in Path(root).parts
    workspace = root + "/project"
    binary = os.environ["ASTRA_LIVE_LINUX_BINARY"]
    model = os.environ["ASTRA_LIVE_MODEL"]
    report = {
        "kind": "real_linux_ssh_native_runtime",
        "result": "FAILED",
        "whole_system_acceptance": False,
        "started_at": time.time(),
        "remote_evidence_root": root,
        "model": model,
        "existing_service_modified": False,
        "native_storage_isolated": True,
    }
    report_path = Path(os.environ["ASTRA_LIVE_LINUX_REPORT"])
    tunnel = None
    try:
        await ssh.connect()
        code, system, _ = await ssh.run_command("uname -srm; getconf GNU_LIBC_VERSION")
        assert code == 0
        report["system"] = system.strip()
        code, _, _ = await ssh.run_command("umask 077; mkdir -p " + shlex.quote(workspace))
        assert code == 0
        await ssh.write_file(workspace + "/test_arithmetic.cjs", TESTS.encode())
        provider = protected_json(os.environ["ASTRA_LIVE_LINUX_PROVIDER_FILE"])
        await ssh.write_file(root + "/provider.json", json.dumps(provider).encode())
        # 指定的模型连接配置只进入 0600 部署文件，不进入模型上下文；不复制旧业务配置。
        bootstrap = """const fs=require('node:fs'), path=require('node:path');
const cp=require('node:child_process');
const net=require('node:net'), crypto=require('node:crypto');
const root=__dirname, ws=path.join(root,'project');
const cfg=JSON.parse(fs.readFileSync(path.join(root,'provider.json'),'utf8'));
for(const d of ['config/opencode','data','state','cache'])
 fs.mkdirSync(path.join(root,d),{recursive:true,mode:0o700});
fs.writeFileSync(path.join(root,'config/opencode/opencode.json'),JSON.stringify({
  provider:cfg.provider, permission:{'*':'deny'}, autoupdate:false
}),{mode:0o600});
const password=crypto.randomBytes(32).toString('hex');
const server=net.createServer();server.listen(0,'127.0.0.1',()=>{const port=server.address().port;
 server.close(()=>{const out=fs.openSync(path.join(root,'runtime.log'),'a',0o600);
 const args=['serve','--pure','--hostname','127.0.0.1','--port',String(port)];
 const child=cp.spawn(process.env.ASTRA_TEST_OPENCODE,args,{
 cwd:ws,detached:true,stdio:['ignore',out,out],env:{...process.env,OPENCODE_SERVER_PASSWORD:password,
 XDG_CONFIG_HOME:path.join(root,'config'),XDG_DATA_HOME:path.join(root,'data'),
 XDG_STATE_HOME:path.join(root,'state'),XDG_CACHE_HOME:path.join(root,'cache')}});
 fs.writeFileSync(path.join(root,'runtime.json'),JSON.stringify({pid:child.pid,port,password}),{mode:0o600});
 child.unref();});});
"""
        await ssh.write_file(root + "/start.cjs", bootstrap.encode())
        command = (
            "cd " + shlex.quote(workspace) + " && git init -q && git add . && "
            "git -c user.name='Astra Runtime Test' -c user.email=test@example.invalid commit -qm baseline && "
            "ASTRA_TEST_OPENCODE=" + shlex.quote(binary) + " node " + shlex.quote(root + "/start.cjs")
        )
        code, _, _ = await ssh.run_command(command)
        assert code == 0
        process = json.loads(await ssh.read_file(root + "/runtime.json"))
        tunnel = await ssh.open_tunnel(remote_port=process["port"])
        client = OpenCodeClient(
            OpenCodeConfig(
                tunnel.base_url,
                "linux-test",
                RuntimePurpose.TASK,
                (workspace,),
                password=process["password"],
                model=model,
            )
        )
        for _ in range(100):
            try:
                report["health"] = await client.verify_contract()
                break
            except Exception:
                await asyncio.sleep(0.2)
        else:
            raise AssertionError("独立 Linux Runtime 未就绪；测试日志仅保留远端")
        rules = [
            {"permission": "*", "pattern": "*", "action": "deny"},
            *(
                {"permission": tool, "pattern": "*", "action": "allow"}
                for tool in ["read", "glob", "grep", "edit"]
            ),
            {"permission": "edit", "pattern": "*test_arithmetic.cjs", "action": "deny"},
            {"permission": "bash", "pattern": "node test_arithmetic.cjs", "action": "allow"},
        ]
        binding = await client.create_session(
            workspace,
            owner_ref="linux-isolated",
            title="Astra 1.0 Linux isolated validation",
            permission_rules=rules,
        )
        prompt_id = "msg" + uuid4().hex
        report["native_session_id"] = binding.native_session_id
        report["prompt_id"] = prompt_id
        await client.prompt_async(
            binding,
            message_id=prompt_id,
            text=(
                "Create arithmetic.cjs exporting {add}. add accepts only finite JavaScript numbers, "
                "throws TypeError for other inputs and returns their sum. "
                "Read the existing test_arithmetic.cjs without modifying it. "
                "Run exactly node test_arithmetic.cjs. No network, installs or other changes."
            ),
        )
        # 在工程进行中关闭转发，使用新本地端口重新连同一远端 Runtime/Session，不能重发 prompt。
        await tunnel.close()
        tunnel = await ssh.open_tunnel(remote_port=process["port"])
        client = OpenCodeClient(
            OpenCodeConfig(
                tunnel.base_url,
                "linux-test",
                RuntimePurpose.TASK,
                (workspace,),
                password=process["password"],
                model=model,
            )
        )
        recovered = NativeSessionBinding(
            binding.native_session_id,
            binding.runtime_id,
            binding.purpose,
            binding.owner_ref,
            binding.directory,
            binding.permission_digest,
        )
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            tree = await native_tree(client, recovered)
            messages = tree[binding.native_session_id]
            if any(item.get("info", {}).get("error") for item in messages):
                raise AssertionError("Linux 原生模型请求失败，保留具体 Session 供对账")
            if final_message(messages, prompt_id) and (await client.status(recovered))["type"] == "idle":
                break
            await asyncio.sleep(0.5)
        else:
            raise AssertionError("Linux 工程超时，保留原 Session 和证据")
        code, stdout, _ = await ssh.run_command(
            "cd " + shlex.quote(workspace) + " && node test_arithmetic.cjs"
        )
        assert code == 0 and "5 original assertions passed" in stdout
        assert (
            hashlib.sha256(await ssh.read_file(workspace + "/test_arithmetic.cjs")).hexdigest()
            == hashlib.sha256(TESTS.encode()).hexdigest()
        )
        tools = [
            part
            for rows in tree.values()
            for message in rows
            for part in message.get("parts", [])
            if part.get("type") == "tool"
        ]
        assert any(
            part.get("tool") == "bash"
            and part.get("state", {}).get("metadata", {}).get("exit") == 0
            and "5 original assertions passed" in part.get("state", {}).get("output", "")
            for part in tools
        )
        assert sum(item.get("info", {}).get("id") == prompt_id for item in messages) == 1
        report.update(
            result="PASSED",
            native_session_id=binding.native_session_id,
            independent_test_exit_code=code,
            independent_test_output=stdout,
            original_test_sha256=hashlib.sha256(TESTS.encode()).hexdigest(),
            tunnel_reconnect_same_session=True,
            native_evidence_refs=evidence_index(messages, binding.native_session_id),
            usage=usage_facts(messages),
        )
    except Exception as exc:
        report["failure_type"] = type(exc).__name__
        raise
    finally:
        # 只结束本测试以随机目录记录的 PID；原 4096/业务 Session 不受影响。
        if ssh.is_active():
            await ssh.run_command(
                "node -e "
                + shlex.quote(
                    "const fs=require('fs'),root=" + json.dumps(root) + ";"
                    "try{const p=JSON.parse(fs.readFileSync(root+'/runtime.json'));"
                    "if(fs.readlinkSync('/proc/'+p.pid+'/cwd')===root+'/project'&&"
                    "fs.readFileSync('/proc/'+p.pid+'/cmdline','utf8').split('\\0').includes('serve'))"
                    "process.kill(p.pid,'SIGTERM')}catch{}"
                )
            )
        if tunnel:
            await tunnel.close()
        await ssh.close()
        report["finished_at"] = time.time()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
