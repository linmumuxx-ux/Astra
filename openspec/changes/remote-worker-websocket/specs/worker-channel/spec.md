## ADDED Requirements

### Requirement: Worker identity is independent of the employee
The system MUST bind one Worker instance to one execution environment and MUST identify it with `worker_instance_id`. The system MUST NOT use the digital employee id as that identity. Enrollment MUST return the token once and store only its digest.

#### Scenario: Enrollment hides the token
- **WHEN** an operator enrolls an execution environment and later reads the Worker
- **THEN** the enrollment response contains the token and the stored row and later reads do not

#### Scenario: Re-enrollment keeps the instance
- **WHEN** the same environment is enrolled again
- **THEN** the instance id is unchanged, the previous token no longer authenticates, and the epoch increases

### Requirement: One connection epoch is current
The system MUST increment the epoch when a connection authenticates. After a newer epoch is stored, a disconnect or response from an older epoch MUST NOT change the Worker status or command result.

#### Scenario: Stale response is ignored
- **WHEN** a command was stored for an older epoch and that epoch later sends its result
- **THEN** the command status stays unchanged

#### Scenario: Old disconnect keeps the new connection
- **WHEN** the old connection closes after a newer epoch is online
- **THEN** the Worker remains online at the newer epoch

### Requirement: Commands are durable and idempotent
The system MUST store a command before publishing it. The same `request_id` with the same Worker, command name, and payload MUST return the stored command and MUST NOT publish it again. A conflicting Worker, name, or payload MUST be rejected. An offline Worker MUST persist the command as failed with `offline`. A full control queue MUST leave the command pending and `unpublished`. A publish whose result is unknown MUST leave the command `uncertain` and MUST NOT roll the attempt back. Idempotent commands that are still `pending` MAY be retried by the same-epoch owner after the dispatch lease expires. Accepted commands MUST NOT be republished. A newer epoch MUST NOT adopt the previous epoch's commands. A side-effect command such as `prompt` MUST NOT be published again after it leaves `unpublished`.

#### Scenario: Duplicate request is not delivered twice
- **WHEN** a caller submits a request id that is already stored
- **THEN** the original command is returned and the route publishes once

#### Scenario: Publish sees the stored row
- **WHEN** the route publishes a new command
- **THEN** the command row is already pending

### Requirement: Routing has one owner
The process holding the socket MUST be the only owner for that epoch. Registration MUST reject an older epoch, including after the current lease is cleared or expires. Another memory bus MUST NOT observe that owner. Redis clients using the same prefix MUST observe it. Clearing an older epoch or a different owner MUST leave the current lease in place. Publish, consume, and send MUST fence on the target epoch. A consumer that loses ownership MUST stop. Control frames MUST be delivered before queued events, and a full event queue MUST drop events instead of blocking control. Local heartbeat frames MUST NOT release Redis queue capacity.

#### Scenario: Separate memory buses do not share ownership
- **WHEN** one memory bus records an owner
- **THEN** a second memory bus does not return that owner

#### Scenario: Stale lease clear is ignored
- **WHEN** the current lease is epoch 2 and a caller clears epoch 1
- **THEN** the epoch 2 lease remains

### Requirement: Configured Redis is the default bus
When the bus setting is `auto` and the Redis URL is non-empty, the gateway MUST use the Redis bus. When that URL is empty, the gateway MUST use the memory bus and its health payload MUST include the warning `仅单进程可用`. An explicit `memory` or `redis` setting MUST override the automatic choice. Redis queue admission MUST reject a frame once the list length plus frames already pulled but not delivered reaches the limit, and the check plus enqueue MUST be one atomic operation.

#### Scenario: Automatic Redis
- **WHEN** the bus setting is `auto` and a Redis URL is configured
- **THEN** the health payload reports `redis` and has no single-process warning

#### Scenario: Bounded Redis admission
- **WHEN** one command is already queued and the control limit is 1
- **THEN** the next command is rejected even if a consumer has moved the queued command out of the Redis list and not yet delivered it

### Requirement: Disconnect does not restart OpenCode
The Worker Agent MUST reconnect with backoff after a socket failure and MUST NOT count that failure as an OpenCode process restart.

#### Scenario: Reconnect keeps the restart count
- **WHEN** the socket closes and the agent connects again
- **THEN** the new session receives a new epoch and the process restart count stays unchanged

### Requirement: Migrated environments are explicitly marked
The system MUST store `worker_channel` as `ssh` or `worker` on the execution environment row. Every `connect()` entry and both environment resolvers MUST read that column by `environment_id` and MUST NOT take it from a task or session snapshot. A Worker instance row alone MUST NOT select the Worker transport. Changing the mark MUST be a maintenance operation refused while the employee is occupied. The probe MUST request only the configured Gateway and MCP addresses and MUST NOT accept a URL supplied in a command. After a controlled reload, the system MUST verify the effective OpenCode configuration, including project-level overrides, before storing `worker`. OpenCode MUST keep listening on `127.0.0.1`. For an environment marked `worker`, workspace directory preparation MUST be an Agent command. File browsing, Git reads, and uploads remain on SSH until the worker-local file requirements below are implemented; that implementation MUST NOT open SSH for those calls. An environment still marked `ssh` MUST keep the existing SSH path until phase 4.

#### Scenario: Enrollment alone does not migrate
- **WHEN** an environment has a Worker instance and `worker_channel` is still `ssh`
- **THEN** OpenCode HTTP continues to use the existing SSH path

#### Scenario: Migration requires a successful intranet probe
- **WHEN** the Worker cannot reach the configured intranet Gateway or MCP endpoint
- **THEN** `worker_channel` stays `ssh`

#### Scenario: Snapshot does not select the transport
- **WHEN** a stored environment snapshot omits `worker_channel` or contains a stale value
- **THEN** `connect()` uses the current environment row

#### Scenario: Command URL is not probed
- **WHEN** a command payload names a Gateway URL other than the configured address
- **THEN** the migration probe does not request that URL

### Requirement: OpenCode HTTP uses a worker-initiated data channel
For an environment marked `worker`, Nexus MUST publish only a short ready notice on the WebSocket. The notice contains the request id, epoch, and deadline, and MUST NOT contain the request or response body. The Worker MUST fetch the body with `GET /api/worker-gateway/data/{request_id}/request` and upload the response with `PUT /api/worker-gateway/data/{request_id}/response`. The upload MUST authenticate with the enrollment token and the command epoch, and MUST carry the response headers needed by callers, including `x-next-cursor`. Each upload attempt MUST use its own staging key. A failed attempt MUST NOT delete another attempt's body. The request-body key MUST remain available until the command deadline plus the dispatch-lease margin. An older epoch MUST be rejected without returning or storing the body. After its epoch ends, the Agent MUST NOT start the local POST. A request or non-stream response larger than 8 MiB MUST fail. The local call MUST stop at the control timeout. The Workspace proxy MUST use this transport instead of dialing `client.base_url` directly. HTTP work MUST run outside the Agent read loop so heartbeat and cancel stay responsive.

#### Scenario: Large response stays off the socket
- **WHEN** a migrated Worker completes an OpenCode HTTP call
- **THEN** the WebSocket carries only the ready notice, and the response body and headers are stored from the HTTP upload

#### Scenario: Stale data upload is rejected
- **WHEN** a data upload carries an epoch older than the Worker instance
- **THEN** the upload is rejected and no response body is stored

### Requirement: OpenCode events are sequenced WebSocket frames
The Agent MUST assign a per-epoch, per-directory sequence and send each fitting OpenCode SSE event as a WebSocket event frame. One local SSE read MUST exist per Worker, epoch, and directory. The shared log MUST retain the last N events. Consumer cursors MUST expire unless renewed. When the slowest unexpired consumer is N events behind, Nexus MUST send `pause_events` and later `resume_events`. When no unexpired consumer remains, Nexus MUST send `stop_events` and drop that subscription. An event larger than the frame limit MUST be reported as `astra.event_gap` without uploading its payload. Gap refreshes for one task MUST be coalesced into a single reread of the native Session, the full message pages, questions, and permissions. An event from an older epoch MUST NOT advance the cursor. Reconnect MUST NOT create a Session to fill a gap.

#### Scenario: Oversized event becomes a gap
- **WHEN** an OpenCode event exceeds the WebSocket frame limit
- **THEN** consumers receive `astra.event_gap` and recovery rereads the native Session without creating a new one

### Requirement: Only an explicit human retry may resend a prompt
`pending_message_id`, `pending_prompt.in_flight`, `pending_attempt`, and the mapping from that attempt to the Worker request id MUST be committed before the call leaves Nexus. The system MUST record whether the Agent fetched that attempt's request body. Reconnect, recovery, dispatch, heartbeat, and timeout paths MUST NOT call the human retry. A command that was stored but whose body was never fetched is the only evidence that the prompt was not sent. A fetched body with no visible message is an unknown result: the human retry MUST wait for the local call cap plus the persistence margin, and MUST NOT post until the person confirms again. An expired command row or a newer epoch is not that evidence. OpenCode 1.18.35 returns 204 from `promptAsync` before the user message is stored and does not deduplicate `messageID`. A visible message id MUST NOT be posted again. A failed read MUST leave `in_flight` set. Reconnect MUST NOT create a Session.

#### Scenario: Accepted prompt survives an agent exit
- **WHEN** the full message pages contain the pending message id and the Agent exits before uploading the result
- **THEN** reconnect observes that message, does not send the prompt again, and does not create a Session

#### Scenario: Concurrent manual retries post once
- **WHEN** two human retries claim the same pending message at the same time
- **THEN** only one compare-and-set succeeds and only that attempt may post

#### Scenario: A fetched body is not proof of a missed send
- **WHEN** the Agent has fetched the prompt body and the message is not yet visible
- **THEN** the human retry does not post again until the local cap and persistence margin have passed and the person confirms

#### Scenario: An unfetched body may be sent again
- **WHEN** the prompt command is stored, its request body was never fetched, and the full message pages do not contain the id
- **THEN** an explicit human retry may post that same message id once

### Requirement: Transport faults stay out of task status
A communication failure MUST set `runtime_connection` to `UNAVAILABLE` and MUST leave `Task.status` unchanged. An execution timeout and an OpenCode session error MUST be projected only through `RuntimeService.apply_session_state()`. Worker Gateway code MUST NOT assign `Task.status`. An environment marked `worker` that loses its socket MUST NOT open an SSH tunnel and MUST NOT run the start script that kills an existing OpenCode process. A WebSocket disconnect MUST NOT restart a healthy OpenCode.

#### Scenario: Disconnect keeps the business status
- **WHEN** the Worker socket closes during a running task on a migrated environment
- **THEN** the task business status is unchanged, the runtime connection is `UNAVAILABLE`, and no SSH tunnel is opened

### Requirement: Worker occupancy has one predicate
Projection, heartbeat, dispatch, start, send, maintenance, and cancel completion MUST use one occupancy predicate. The predicate MUST ignore unclaimed `PENDING` tasks. A claimed or bound task occupies its employee unless the task is `SUCCEEDED`, or it is `CANCELED` or canceling and a human release still matches its current Session and `pending_attempt`. `RUNNING` and `WAITING` MUST remain occupied even when `execution_stop_confirmed_at` is set. `FAILED`, a broken binding, and a canceled task whose stop is unconfirmed MUST occupy the employee. Socket presence, session idle, and command completion MUST NOT release occupancy. `current_task_count` MUST be written only from this predicate. Heartbeat MUST NOT clear it independently, and dispatch MUST NOT use `current_task_count < 1` as a separate rule. Maintenance MUST additionally refuse while the employee has a Session in `RUNNING`, `WAITING`, or `UNKNOWN` without a still-valid human release. Human release MUST be explicit, MUST apply only to a canceled or canceling task, MUST record the operator, reason, Session, and attempt, and MUST be cleared by a new attempt, restart, or new Session. Communication failure MAY set a Session to `UNKNOWN` and that status MUST NOT by itself prove that execution has stopped.

#### Scenario: Session success does not free the worker
- **WHEN** the native Session has succeeded and the task is still `WAITING` for human confirmation
- **THEN** the employee remains occupied

#### Scenario: Unconfirmed cancel keeps the worker
- **WHEN** a task is `CANCELED` and its Session is still `UNKNOWN`
- **THEN** the employee remains occupied and heartbeat does not clear the occupancy count

#### Scenario: Human confirmation releases only a canceled task
- **WHEN** a person confirms that execution has stopped for a `CANCELED` task whose Session remains `UNKNOWN`
- **THEN** the release records the operator, reason, Session, and attempt, and the task is not marked succeeded

#### Scenario: A running task stays occupied after a stale confirmation
- **WHEN** a task is `RUNNING` or `WAITING` and an older stop confirmation is still stored
- **THEN** the employee remains occupied

#### Scenario: Unclaimed work does not occupy the employee
- **WHEN** an employee has only unclaimed `PENDING` tasks
- **THEN** the occupancy predicate is false and dispatch can still claim one

### Requirement: Command identity includes the session
The same `request_id` MUST return the stored command only when the Worker, command name, payload, and `session_id` all match. A different `session_id`, including null versus non-null, MUST be rejected with a conflict. A cancel MUST use its own request id and carry `target_request_id` in the payload. Canceling the HTTP wait MUST NOT abort the native OpenCode session; task cancellation MUST still call the native abort.

#### Scenario: Same request id on another session conflicts
- **WHEN** a stored request id is submitted again with a different session id
- **THEN** the command is rejected and the original row is not returned as a replay

#### Scenario: Cancel does not reuse the target request id
- **WHEN** a caller cancels an in-flight HTTP command
- **THEN** the cancel is stored under a new request id whose payload names the target, and the native session is not aborted by that cancel

### Requirement: Epoch changes fence a claim and an in-flight upload
Authorization to fetch or execute a command MUST come from the database epoch and command row. The Redis owner MUST only choose the publishing process. A command claimed before an epoch change MUST NOT be executed on the new epoch. The final upload update MUST include a subquery that the Worker instance epoch is still current, in the same form as response application. An upload that loses this update MUST delete only its own staging key and MUST NOT wake the waiter or change `Task.status`.

#### Scenario: Epoch moves while a body is uploading
- **WHEN** the Worker epoch changes after a response upload has started and before its final update
- **THEN** the final update does not succeed, the waiter does not receive that body, and the task status stays unchanged

### Requirement: Migrated file, Git, and upload work runs on the Worker
For an environment marked `worker`, path checks, read-only Git, worktree file reads, and uploads MUST be Worker commands and MUST NOT call `open_session` or `run_remote`. The commands are `validate_path`, `git_readonly`, `read_file`, and `upload_file`. An environment marked `ssh` MUST keep the existing SFTP and remote-command path until phase 4. Directory and worktree preparation stays the phase 2 `prepare_workspace` command. The Worker Agent MUST NOT treat these commands as Task or Session transitions. Migrated file, Git, and upload calls MUST NOT read the SSH password copied by `session_connection.py` at the environment resolvers.

`validate_path` carries `workspace` and `path` and returns `{relative}`. It MUST first open the full relative path from the workspace directory fd with `openat2` using `O_PATH`, `RESOLVE_BENEATH`, and `RESOLVE_NO_MAGICLINKS`. Only when that open returns `ENOENT` MAY it open the parent the same way, and it MUST return `{relative}` when the parent opens. A final component that is a symlink to a path outside the workspace MUST fail as `symlink_escape` and MUST NOT succeed merely because its parent opened. `EXDEV` or `ELOOP` MUST be `symlink_escape`. `ENOSYS`, or `EPERM` caused by seccomp, MUST be `io`. `git_readonly` carries `workspace`, a closed `operation` name, and only the revision, baseline, or path that operation uses. Its result is `{code, size, sha256}`. `read_file` carries `workspace` and `path` and returns `{size, sha256, missing}`. `upload_file` carries `workspace`, `filename`, `size`, and `sha256`, and returns `{path}` in the existing `{workspace}/uploads/{id}-{filename}` shape. A missing worktree file on `read_file` MUST return `missing=true` and an empty body. A non-zero Git status on `GET /repo` MUST still become an empty string, except that `too_large` from `status_porcelain` MUST set `dirty` to true.

`git_readonly` MUST build argv only for `head`, `inside_work_tree`, `git_common_dir`, `branch`, `status_porcelain`, `origin_url`, `rev_list`, `diff_name_status_range`, `diff_numstat`, `ls_files_others`, `show_file`, `diff_patch`, and `diff_name_status_file`, using the flags already used by the SSH implementation, plus a fixed `-c core.fsmonitor=false`. A caller-supplied `-c` MUST be rejected. A revision MUST be `HEAD` or 4 to 64 hexadecimal characters. The command MUST run with `child_environ()`. The Agent MUST kill git at the command deadline and return `code=124` with empty output. Any other operation MUST fail as `unsupported_operation`. Git MAY resolve paths again after the command starts; that window is the same one SSH already has.

These four commands MUST run on an Agent task table guarded by a semaphore of 4. They MUST NOT run inside the socket read loop, MUST NOT consume an OpenCode HTTP slot, and MUST NOT take a database slot. Closing the socket MUST cancel that table the same way in-flight HTTP tasks are cancelled.

File API routes `/file`, `/file/content`, `/file/status`, and `/find/file` MUST run `validate_path` and then the existing OpenCode `http` exchange. They MUST NOT be reimplemented in the Agent. OpenCode MAY resolve the path again after `validate_path`; that window is the same one SSH already has. `/find` and `/find/symbol` keep their current lexical check.

#### Scenario: Migrated browsing does not open SSH
- **WHEN** a worker-channel environment lists files, reads a diff, or loads the task repo
- **THEN** the platform dispatches Worker commands and does not open an SSH session or read the copied SSH password

#### Scenario: SSH environments keep the old path
- **WHEN** the environment is still marked `ssh`
- **THEN** file and Git calls use the existing SFTP and remote-command path

#### Scenario: A deleted file still has a diff
- **WHEN** a diff lists a file whose final path component is missing
- **THEN** `validate_path` returns the relative path and the diff result includes that file

#### Scenario: Porcelain over the size cap marks the repo dirty
- **WHEN** `status_porcelain` fails as `too_large` while loading the task repo
- **THEN** the repo response sets `dirty` to true

### Requirement: File bytes use the existing data channel
WebSocket command results MUST stay within the configured frame limit and MUST NOT contain file bytes or Git stdout. Non-empty Git stdout and file contents MUST use `GET /api/worker-gateway/data/{request_id}/request` and `PUT /api/worker-gateway/data/{request_id}/response`. Empty Git stdout MUST NOT start a PUT. OpenCode `http` bodies MUST remain capped at 8 MiB. Chunk size stays 256 KiB. No third transport and no new data route are added.

`read_file` and `git_readonly` responses MUST place base64 of the raw bytes into the existing UTF-8 text chunks. `size`, `sha256`, and the 20 MiB cap MUST be computed on those raw bytes. The text-chunk assembly limit MUST fit the base64 of 20 MiB and MUST NOT be applied to the string produced by utf-8 replacement. Nexus MUST base64-decode the chunks and then decode the raw bytes as utf-8 with replacement, matching the current SSH stdout and diff-file decoding. The `upload_file` GET on that same request URL MUST return the raw bytes with `application/octet-stream` and `X-Astra-Sha256`. The JSON body used by `http` MUST stay unchanged.

#### Scenario: A large upload stays off the socket
- **WHEN** a browser uploads a file on a migrated environment
- **THEN** the WebSocket carries the command descriptor and checksum, and the Worker reads the bytes from the existing data-channel GET

#### Scenario: A binary git blob keeps its checksum
- **WHEN** `show_file` returns bytes that are not valid utf-8
- **THEN** the data channel stores base64 of those bytes, `sha256` matches the raw bytes, and Nexus applies utf-8 replacement only after decoding the base64

### Requirement: Worker file access keeps the current limits
The Worker MUST open the workspace with `openat2` from a directory fd of the configured workspace root or the existing `.astra-tasks` sibling, using `RESOLVE_BENEATH` and `RESOLVE_NO_MAGICLINKS`. It MUST NOT realpath the workspace and then open that string. `read_file` and `upload_file` MUST use that `openat2` open as their atomic file open. Writes MUST use `O_CREAT`, `O_EXCL`, and `O_NOFOLLOW` with mode `0600`, and the final rename MUST use `RENAME_NOREPLACE`. The `uploads` directory MUST be opened with `O_DIRECTORY` and `O_NOFOLLOW`. Lexical checks MUST reject NUL, backslash, `..`, and a case-sensitive `.git` path component before the open. The Worker MUST repeat those checks and MUST NOT trust the caller.

`RESOLVE_BENEATH` MUST reject an absolute symlink even when its target is inside the workspace. A relative symlink that stays inside the workspace MUST remain readable. The implementation MUST NOT widen any current remote limit: the 20 MiB upload and per-file diff caps on raw bytes, the single-component upload name, the exclusive create, the fixed Git flags, or the returned posix path. A checksum mismatch MUST NOT create a file. Git stdout above 20 MiB of raw bytes MUST fail as `too_large`. The browser write surface MUST remain `POST /files/{filename}` and `data:` prompt attachments.

A local partial file named `uploads/.partial-{request_id}` MUST be removed when the command fails before rename. The startup sweep MUST only visit `{allowed-root}/*/uploads/.partial-*` and `{parent-of-allowed-root}/.astra-tasks/*/uploads/.partial-*`, and MUST NOT follow symlinks. A failed or conflicting upload MUST delete only its own staged object. After rename, a failed epoch compare-and-set MUST leave the mode-`0600` random-named file in place and MUST NOT wake the waiter. The Gateway MUST wake the waiter only when that update's rowcount is 1.

On socket close the Agent MUST cancel the upload task and set that connection's `closed` event from `run_session`'s `finally`. Disconnect cleanup does not change the connection epoch. Inside the blocking function, which cannot be cancelled while it is running in a worker thread, the Agent MUST check both `closed` and its epoch once before creating the partial file and once before rename. Either a set `closed` event or a changed epoch MUST NOT create or rename the file.

#### Scenario: A symlink cannot leave the workspace
- **WHEN** the final component of a requested path is a symlink to a file outside the workspace
- **THEN** `validate_path` fails with `symlink_escape` and does not return that relative path

#### Scenario: An absolute in-workspace symlink is rejected
- **WHEN** a path component is an absolute symlink whose target is inside the workspace
- **THEN** the command fails and does not return that target

#### Scenario: A bad checksum writes nothing
- **WHEN** the fetched upload bytes do not match the command checksum
- **THEN** the Worker creates no file and reports `checksum_mismatch`

#### Scenario: A failed compare-and-set leaves the renamed file
- **WHEN** the upload has been renamed and the final command update does not match one row
- **THEN** the mode-`0600` file remains, the waiter is not woken, and the task status stays unchanged

### Requirement: Browser workspace responses stay the same
The platform MUST keep these URLs and response shapes: `GET /api/tasks/{id}/workspace`; `POST /api/tasks/{id}/files/{filename}` returning `{"path": path}` and 413 above 20 MB; the existing OpenCode proxy methods and filters; `GET` diff as the current JSON list and raw diff as `text/x-diff`; event streams as `text/event-stream` with the current cache headers and `data:` lines; `GET /api/tasks/{id}/repo` returning `name`, `branch`, `commit`, `dirty`, `changes`, and `task_changes`. Prompt `data:` parts MUST still be rewritten to a file URI. `dirty` MUST be true when `status_porcelain` is `too_large`.

#### Scenario: Diff response shape is unchanged
- **WHEN** a browser requests the task diff on a migrated environment
- **THEN** the response is the existing JSON list or `text/x-diff` body

### Requirement: File command failure does not change task status
Read commands MAY be dispatched again after the same-epoch lease expires, and a newer epoch MAY run them again. `upload_file` MUST NOT be published again after it leaves `unpublished`. Closing the socket MUST cancel an in-flight upload and set that connection's `closed` event. The blocking upload MUST check both `closed` and the epoch before creating its partial file and again before rename, and MUST NOT create or rename when `closed` is set or the epoch has changed. A failed compare-and-set MUST NOT report success and MUST NOT require the Agent to delete a file that was already renamed. No file or Git command failure may assign `Task.status` or call `apply_session_state()`. `workspace_head_commit` MUST still return no commit on failure, and workspace change collection MUST still return an empty object. A migrated environment MUST NOT open SSH when one of these commands fails. Reconnect MUST NOT create a Session or resend a prompt because of these commands.

#### Scenario: An offline read leaves the task status
- **WHEN** the Worker is offline during a repo or diff read
- **THEN** the command is failed with `offline`, the browser receives the existing error, and the task status is unchanged

#### Scenario: A dropped upload is not sent again
- **WHEN** the Worker socket closes before the partial file is created, including while the blocking function is still running and the connection epoch is unchanged
- **THEN** no file is created, the upload is not dispatched again, and the task status is unchanged
