"""Runtime 基础设施错误；不转换成 Task 或 Employee 的业务终态。"""

from __future__ import annotations


class OpenCodeError(RuntimeError):
    """不包含原始响应正文、提示词或凭据的公开错误。"""


class OpenCodeUnavailable(OpenCodeError):
    def __init__(self, message: str, *, outcome_uncertain: bool = False):
        super().__init__(message)
        self.outcome_uncertain = outcome_uncertain


class OpenCodeIncompatible(OpenCodeError):
    pass


class OpenCodeAuthenticationError(OpenCodeError):
    pass


class NativeSessionNotFound(OpenCodeError):
    pass


class NativeSessionScopeError(OpenCodeError):
    pass


class OpenCodeRequestRejected(OpenCodeError):
    pass


class OpenCodeEventStreamInterrupted(OpenCodeUnavailable):
    """调用者必须重新查询原生事实；不可据此认定执行失败或重新派工。"""


class WorkspaceUnsafe(RuntimeError):
    pass
