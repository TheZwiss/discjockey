import { describe, expect, it } from 'vitest';
import Ajv2020 from 'ajv/dist/2020';
import schema from '$fixtures/hub_events.schema.json';
import { createFakeBridge, pageScenarios } from './bridge';
import { consoleEvent, setConsole } from './console';

const validate = new Ajv2020({ strict: false }).compile(schema);
const stateOf = (scenario: string) => createFakeBridge(scenario)._ctx.s;

describe('the Terminal job in the fake backend', () => {
  it('a Terminal sync is the default of a state with only console_running set (the pages\' own fakes)', () => {
    const s = stateOf('normal');
    s.console_running = true;
    expect(consoleEvent(s)).toEqual({ type: 'ConsoleBusy', running: true, job: 'job:00000c0d', kind: 'sync', line: '4 of 60',
      text: 'Sync running in the Terminal · 4 of 60' });
  });

  it('says what each scenario holds the library with, and nothing once it has ended', () => {
    const tidy = stateOf('console:tidy');
    expect(consoleEvent(tidy)).toMatchObject({ running: true, kind: 'tidy', line: '12 of 80 · Techno',
      text: 'Tidy-up running in the Terminal · 12 of 80 · Techno' });
    const unknown = stateOf('console:unknown');
    expect(consoleEvent(unknown)).toEqual({ type: 'ConsoleBusy', running: true, job: null, kind: null, line: null,
      text: 'A Discjockey command is running in the Terminal' });
    setConsole(unknown, false);
    expect(consoleEvent(unknown)).toEqual({ type: 'ConsoleBusy', running: false, job: null, kind: null, line: null, text: null });
  });

  it('the scenarios are offered by name, and the plain console scenario still holds a Terminal sync', () => {
    expect(Object.keys(pageScenarios())).toEqual(expect.arrayContaining(['console:tidy', 'console:unknown']));
    expect(consoleEvent(stateOf('console'))).toMatchObject({ running: true, kind: 'sync', text: 'Sync running in the Terminal · 4 of 60' });
  });

  it('every ConsoleBusy event fits the engine\'s schema', () => {
    for (const scenario of ['console', 'console:tidy', 'console:unknown', 'normal']) {
      const s = stateOf(scenario);
      for (const running of [true, false]) {
        if (!running) setConsole(s, false);
        const e = consoleEvent(s);
        expect(validate(e), `${scenario} ${running}: ${JSON.stringify(validate.errors)}`).toBe(true);
      }
    }
  });
});

describe('job_status in the fake backend', () => {
  const holderOf = async (scenario: string) => {
    const r = await createFakeBridge(scenario).job_status() as { ok: true; console_running: boolean; console: unknown };
    return [r.console_running, r.console];
  };
  it('answers the holder the scenario holds the library with, and null when none does', async () => {
    expect(await holderOf('normal')).toEqual([false, null]);
    expect(await holderOf('console')).toEqual([true, { job: 'job:00000c0d', via: 'terminal', kind: 'sync', line: '4 of 60',
      text: 'Sync running in the Terminal · 4 of 60' }]);
    expect(await holderOf('console:tidy')).toEqual([true, { job: 'job:00000c0d', via: 'terminal', kind: 'tidy',
      line: '12 of 80 · Techno', text: 'Tidy-up running in the Terminal · 12 of 80 · Techno' }]);
    expect(await holderOf('console:unknown')).toEqual([true, { job: null, via: null, kind: null, line: null,
      text: 'A Discjockey command is running in the Terminal' }]);
  });
});
