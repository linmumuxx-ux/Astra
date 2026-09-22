import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { SuperpowersPlugin } from '../../.opencode/plugins/superpowers.js';

const ASTRA_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

const makeOutput = () => ({
  messages: [
    {
      info: { role: 'user', sessionID: 'ses_test' },
      parts: [{ type: 'text', text: '你好' }],
    },
  ],
});

const injected = async () => {
  const plugin = await SuperpowersPlugin({ client: null, directory: ASTRA_ROOT });
  const output = makeOutput();
  await plugin['experimental.chat.messages.transform']({}, output);
  return output.messages[0].parts.some(
    (part) => part.type === 'text' && part.text.includes('EXTREMELY_IMPORTANT'),
  );
};

process.env.ASTRA_RUNTIME_ROLE = 'platform-assistant';
assert.equal(await injected(), false, 'assistant runtime must not receive the superpowers bootstrap');

delete process.env.ASTRA_RUNTIME_ROLE;
assert.equal(await injected(), true, 'repository-root developer session should receive the bootstrap');

console.log('ok: assistant runtime skips superpowers bootstrap');