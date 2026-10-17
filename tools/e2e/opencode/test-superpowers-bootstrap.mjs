import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { SuperpowersPlugin } from '../../../.opencode/plugins/superpowers.js';

const ASTRA_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..');

const makeOutput = () => ({
  messages: [
    {
      info: { role: 'user', sessionID: 'ses_test' },
      parts: [{ type: 'text', text: '你好' }],
    },
  ],
});

const injected = async (env = {}) => {
  const previous = { ...process.env };
  Object.assign(process.env, env);
  try {
    const plugin = await SuperpowersPlugin({ client: null, directory: ASTRA_ROOT });
    const output = makeOutput();
    await plugin['experimental.chat.messages.transform']({}, output);
    return output.messages[0].parts.some(
      (part) => part.type === 'text' && part.text.includes('EXTREMELY_IMPORTANT'),
    );
  } finally {
    for (const key of Object.keys(process.env)) delete process.env[key];
    Object.assign(process.env, previous);
  }
};

// Default: the bootstrap stays off so a normal task does not inherit the whole
// brainstorm → plan → subagent controller workflow. Skills remain registered
// and loadable through the native `skill` tool.
assert.equal(await injected(), false, 'developer session must not get the bootstrap by default');
assert.equal(
  await injected({ ASTRA_SUPERPOWERS_BOOTSTRAP: '0' }),
  false,
  'an explicit non-1 value keeps the bootstrap off',
);

// Opt-in restores the upstream automatic skill-check workflow.
assert.equal(
  await injected({ ASTRA_SUPERPOWERS_BOOTSTRAP: '1' }),
  true,
  'ASTRA_SUPERPOWERS_BOOTSTRAP=1 should inject the bootstrap',
);

// The platform assistant must never receive it, not even when the switch is on.
assert.equal(
  await injected({ ASTRA_RUNTIME_ROLE: 'platform-assistant', ASTRA_SUPERPOWERS_BOOTSTRAP: '1' }),
  false,
  'assistant runtime must not receive the superpowers bootstrap',
);

console.log('ok: superpowers bootstrap is opt-in and never reaches the assistant runtime');
