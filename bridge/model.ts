// Execute Kimi's low-level requesters, not a coding agent, session or tool runner.
import OpenAI from 'openai';
import Anthropic from '@anthropic-ai/sdk';
import { Agent, EnvHttpProxyAgent, fetch as transportFetch } from 'undici';
import { createOpenAIRequester, openAIBase } from '#native/llm/requester/bases/openai/requester';
import { createOpenAIResponsesRequester, openAIResponsesBase } from '#native/llm/requester/bases/openai-responses/requester';
import { createAnthropicRequester, anthropicBase } from '#native/llm/requester/bases/anthropic/requester';
import { defaultOpenAITool } from '#native/llm/requester/bases/openai/format';
import { defaultOpenAIResponsesTool } from '#native/llm/requester/bases/openai-responses/format';
import { createMessageAccumulator, extractText } from '#native/llm/message';
import { resolveThinkingEffortForModel, resolveThinkingKeep } from '#native/llm/thinking';
import { kimiOpenAITrait, kimiAnthropicTrait } from '#native/llm-kimi/trait';

async function main() {
  let raw = '';
  process.stdin.setEncoding('utf8');
  for await (const chunk of process.stdin) {
    raw += chunk;
    if (Buffer.byteLength(raw) > 64 * 1024 * 1024) throw new Error('request_limit');
  }
  const input = JSON.parse(raw);
  const c = input.connection;
  const origin = new URL(c.base_url);
  const loopback = ['127.0.0.1', '[::1]', 'localhost'].includes(origin.hostname);
  if (origin.username || origin.password || origin.search || origin.hash ||
      (origin.protocol !== 'https:' && !(loopback && origin.protocol === 'http:'))) throw new Error('unsafe_endpoint');
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), input.timeout_seconds * 1000);
  const dispatcher = loopback ? new Agent() : new EnvHttpProxyAgent();
  let wireBytes = 0;
  let limited = false;
  const fetch = async (url: any, init: any) => {
    const target = new URL(typeof url === 'string' || url instanceof URL ? url : url.url);
    if (target.origin !== origin.origin) throw new Error('endpoint_changed');
    const response = await transportFetch(url, {...init, dispatcher, redirect: 'error', signal: controller.signal});
    if (!response.body) return response;
    const stream = response.body.pipeThrough(new TransformStream({transform(chunk, sink) {
      wireBytes += chunk.byteLength;
      if (wireBytes > Math.min(64 * 1024 * 1024, input.max_response_bytes * 16)) {
        limited = true; controller.abort(); throw new Error('response_limit');
      }
      sink.enqueue(chunk);
    }}));
    return new Response(stream, {status:response.status,statusText:response.statusText,headers:response.headers});
  };
  let accumulator = createMessageAccumulator();
  let finish: any;
  let failure: any;
  let done = false;
  let usedBytes = 0;
  let usage: any;
  try {
    const options = c.options || {};
    const outputTool = input.output_tool;
    if (outputTool && (input.json_mode || input.tools?.length !== 1 ||
        input.tools[0]?.function?.name !== outputTool.name)) throw new Error('invalid_output_tool');
    const strictOutput = outputTool?.strict === true;
    // Auto is compatible with thinking and gateways that do not support forced tools.
    const choice = strictOutput ? {tool_choice:'required',parallel_tool_calls:false}
      : {tool_choice:'auto'};
    const extraParams: any = !outputTool ? undefined : c.protocol === 'anthropic'
      ? {anthropic:{tool_choice:{type:'auto'}}}
      : c.protocol === 'openai_responses' ? {responses:choice} : {openai:choice};
    const base = c.protocol === 'openai' ? openAIBase
      : c.protocol === 'openai_responses' ? openAIResponsesBase
      : c.protocol === 'anthropic' ? anthropicBase : null;
    if (!base) throw new Error('unsupported_protocol');
    const detected = base.capability?.(c.model) || {image_in:false,video_in:false,audio_in:false,thinking:false,tool_use:true};
    const declared = options.capabilities;
    const capability = Array.isArray(declared) ? {
      image_in:declared.includes('image_in'), video_in:declared.includes('video_in'),
      audio_in:declared.includes('audio_in'), tool_use:declared.includes('tool_use'),
      thinking:declared.some((value: string) => ['thinking','always_thinking'].includes(value)),
    } : detected;
    const model = {
      provider:c.provider_type, model:c.model, baseUrl:c.base_url, apiKey:c.key || undefined,
      defaultHeaders:c.headers, capability, maxContextSize:c.context_window, maxInputSize:c.max_input,
      supportEfforts:options.support_efforts, defaultEffort:options.default_effort, offEffort:options.off_effort,
      alwaysThinking:declared?.includes('always_thinking') === true, adaptiveThinking:options.adaptive_thinking,
    };
    const thinkingEffort = resolveThinkingEffortForModel(undefined, options.thinking_defaults, model, c.provider_type === 'kimi');
    const thinking = {effort:thinkingEffort, keep:resolveThinkingKeep(undefined, options.thinking_keep, thinkingEffort)};
    const clientOptions = (request: any) => ({
      apiKey:c.key || 'unused', baseURL:c.base_url, defaultHeaders:request.headers,
      maxRetries:0, logLevel:'off', fetch,
    });
    const trait = c.provider_type === 'kimi' ? kimiOpenAITrait : {};
    const requester = c.protocol === 'openai'
      ? createOpenAIRequester({trait:{...trait, ...(options.reasoning_key ? {reasoningKey:options.reasoning_key} : {}),
          ...(strictOutput ? {convertTool:(tool: any) => {
            const wire: any = defaultOpenAITool(tool);
            return {...wire,function:{...wire.function,strict:true}};
          }} : {})},
          clientFactory:request => new OpenAI(clientOptions(request) as any)})
      : c.protocol === 'openai_responses'
        ? createOpenAIResponsesRequester({trait:strictOutput ? {convertTool:tool => ({...defaultOpenAIResponsesTool(tool),strict:true})} : undefined,
            clientFactory:request => new OpenAI(clientOptions(request) as any)})
        : createAnthropicRequester({trait:c.provider_type === 'kimi' ? kimiAnthropicTrait : undefined,
            clientFactory:request => new Anthropic({...clientOptions(request),
              ...(c.oauth ? {apiKey:null, authToken:c.key} : {}),
              baseURL:c.base_url.replace(/\/v1\/?$/, ''),
            } as any)});
    const messages = input.messages.filter((m: any) => m.role !== 'system').map((m: any) => {
      if (m.role === 'assistant' && m._native_message) return m._native_message;
      const result: any = {role:m.role, content:[{type:'text',text:m.content || ''}]};
      if (m.role === 'tool') result.toolCallId = m.tool_call_id;
      if (m.role === 'assistant') result.toolCalls = (m.tool_calls || []).map((call: any) => ({
        type:'function',id:call.id,name:call.function.name,arguments:call.function.arguments,
      }));
      return result;
    });
    await requester.generate({
      model, systemPrompt:input.messages.filter((m: any) => m.role === 'system').map((m: any) => m.content).join('\n\n'),
      tools:(input.tools || []).map((tool: any) => tool.function),
      extraParams,
      responseFormat:input.json_mode ? (c.protocol === 'anthropic'
        ? {type:'json_schema',jsonSchema:{name:'memory_summary',strict:true,schema:{
          type:'object',properties:{rollout_summary:{type:'string'},rollout_slug:{type:'string'}},
          required:['rollout_summary','rollout_slug'],additionalProperties:false,
        }}} : {type:'json_object'}) : undefined, thinking,
      maxCompletionTokens:c.max_output, maxContextTokens:Math.min(c.context_window,c.max_input),
    }, {messages}, {signal:controller.signal, onEvent(event: any) {
      if (event.type === 'llm.sent') { accumulator = createMessageAccumulator(); finish=undefined; done=false; }
      if (event.type === 'llm.streaming.part') {
        usedBytes += Buffer.byteLength(JSON.stringify(event.part));
        if (usedBytes > input.max_response_bytes) { limited=true; controller.abort(); throw new Error('response_limit'); }
        accumulator.push(event.part);
      }
      if (event.type === 'llm.streaming.finish') finish = event.finish;
      if (event.type === 'llm.streaming.usage') usage = event.usage;
      if (event.type.startsWith('llm.failed.')) failure = {kind:event.error.kind, status:event.error.statusCode};
      if (event.type === 'llm.done') done = true;
    }});
    if (limited) return {error:'response_limit'};
    if (failure) return {error:'native_request_failed', ...failure};
    if (!done || !['completed','tool_calls'].includes(finish?.finishReason)) {
      return {error:'native_request_incomplete', finish:finish?.finishReason || 'missing'};
    }
    const message = accumulator.finish();
    const result: any = {role:'assistant',content:extractText(message),_native_message:message};
    if (message.toolCalls.length) result.tool_calls = message.toolCalls.map((call: any) => ({
      type:'function',id:call.id,function:{name:call.name,arguments:call.arguments || ''},
    }));
    if (!result.content && !result.tool_calls) return {error:'empty_final_output',kind:'empty_response'};
    const reply = {result, usage};
    if (Buffer.byteLength(JSON.stringify(reply)) > input.max_response_bytes * 2) return {error:'response_limit'};
    return reply;
  } finally {
    clearTimeout(timer);
    await dispatcher.destroy();
  }
}
main().then(result => process.stdout.write(JSON.stringify(result))).catch(() => {
  process.stdout.write(JSON.stringify({error:'native_request_failed'}));
});
