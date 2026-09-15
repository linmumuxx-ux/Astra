---
name: nexus-employee-routing
description: 搜索、查看、比较或推荐 NEXUS 数字员工，以及为任务选择执行员工时使用。基于平台返回的任务类型、分类、可用状态和负载进行选择，禁止凭姓名或模型印象猜测员工能力。
compatibility: opencode
metadata:
  domain: employee
  tools: nexus_employee_*
---

# NEXUS 数字员工选择

员工能力、状态和负载是实时平台事实，必须通过 Tool 获取。

## 选择 Tool

- 用户按姓名、岗位找员工：`nexus_employee_search`。
- 已知 `employee_id` 或需要环境、当前任务等详情：`nexus_employee_get`。
- 用户问“谁适合做”“分给谁”“找一个可用员工”：`nexus_employee_recommend`。

## 推荐流程

1. 已知任务类型时传 `task_type`；已知真实分类 ID 时传 `category_id`。
2. 默认 `only_available=true`。只有用户明确要查看全部候选时才放宽。
3. 按平台返回顺序和 `recommend_reasons` 解释候选，不自行构造评分或能力标签。
4. 若用户关心执行环境是否可用，对候选调用 `nexus_employee_get` 查看 `environment_status` / `environment_mode`，不要把员工状态等同于环境状态。
5. 若没有候选，明确说明当前条件下无可推荐员工；可以建议放宽条件，但不要虚构员工。

## 姓名解析

用户给出员工姓名但没有 ID 时，先 `nexus_employee_search`：

- 唯一明确匹配：使用返回的真实 `employee_id`。
- 多个可能匹配：列出候选并请用户选择。
- 没有匹配：说明未找到，不要拼接或推断 ID。

## 回答要求

介绍员工时优先给出姓名、岗位、状态、当前任务数，以及与当前任务直接相关的推荐原因。不要仅因为名字、岗位描述相似就断言其具备某项能力。
