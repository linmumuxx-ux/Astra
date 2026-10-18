import assert from 'node:assert/strict'
import test from 'node:test'

import { formatContactEmployeeTool } from '../src/features/chat/format.ts'

test('delivered contact_employee result shows a short status, not the raw JSON', () => {
  const parsed = formatContactEmployeeTool('{"employee_name":"小王","message":"看看"}', '{"status":"delivered","employee":"小王"}')
  assert.equal(parsed.text, '已联系 小王')
  assert.equal(parsed.isError, false)
})

test('failed delivery surfaces the real reason', () => {
  const parsed = formatContactEmployeeTool('{"employee_name":"小王"}', '{"status":"failed","employee":"小王","reason":"没有找到可联系的员工：小王"}')
  assert.equal(parsed.text, '联系失败：没有找到可联系的员工：小王')
  assert.equal(parsed.isError, true)
})

test('pending call names the target without claiming a reply', () => {
  assert.equal(formatContactEmployeeTool('{"employee_name":"小王"}', '').text, '正在联系 小王')
})
