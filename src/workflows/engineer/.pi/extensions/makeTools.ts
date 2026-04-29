import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { execSync } from "child_process";
import { Type } from "typebox";

export default function (pi: ExtensionAPI) {
  const targets: Record<string, string> = {
    build: "builds",
    remarks: "builds and saves remarks for",
    validate: "validates",
    run: "runs",
  };
  for (const [target, verb] of Object.entries(targets)) {
    pi.registerTool({
      name: `make_${target}`,
      label: `Runs 'make ${target}' in the current working directory`,
      description: `${verb} the program in the current working directory`,
      async execute(toolCallId, params, signal, onUpdate, ctx) {
        try {
          const output = execSync(`make ${target}`, {
            cwd: ctx.cwd,
            encoding: "utf-8",
          });
          return {
            content: [{ type: "text", text: output }],
            details: {},
          };
        } catch (err: any) {
          const stdout = err.stdout?.toString() ?? "";
          const stderr = err.stderr?.toString() ?? "";
          const status = err.status ?? err.signal ?? "unknown";
          return {
            content: [{
              type: "text",
              text: `make ${target} failed (exit ${status})\n\n--- stdout ---\n${stdout}\n--- stderr ---\n${stderr}`,
            }],
            isError: true,
          };
        }
      },
    });
  }
}
