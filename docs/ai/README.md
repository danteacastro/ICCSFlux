# ICCSFlux AI Reference Docs

Feed these files to any AI (ChatGPT, Claude, Copilot, etc.) to generate valid ICCSFlux Python scripts, project configurations, and automation sequences.

## Workflow

1. **In ICCSFlux:** Open Playground > Python tab > click the **AI** button in the sidebar
2. **Describe** what you want the script to do
3. **Copy** the context to clipboard
4. **In your AI:** Upload the files from this folder, paste the context, and ask for a script
5. **Back in ICCSFlux:** Create a new script, paste the AI-generated code, click Run

## Files

| File | What it contains |
|------|-----------------|
| **AI_Script_Generation_Guide.md** | Complete Python scripting API: `tags`, `outputs`, `session`, `vars`, `pid`, helper classes, sandbox rules |
| **AI_Project_Generation_Guide.md** | Full project JSON schema: channel types, widgets, HMI controls, alarms, interlocks, sequences, variables |
| **AI_Copilot_Agent_Instructions.md** | System prompt for setting up a custom AI agent (Claude Copilot, Custom GPT, etc.) |
| **Example_Project_Reference.json** | Working example project (Heat Exchanger Test Stand) demonstrating correct field names |

## Which files to use

- **Writing a script?** Upload `AI_Script_Generation_Guide.md` + paste your AI context
- **Building a full project?** Upload all 4 files
- **Setting up a custom AI agent?** Follow the instructions in `AI_Copilot_Agent_Instructions.md`

## Safety Note

**Scripts cannot be used for safety purposes.** ICCSFlux enforces safety through hardware interlocks (IEC 61511 latch state machine), not through Python scripts. Scripts run in a sandboxed environment and cannot override safety-held outputs. When your requirements involve safety-critical operations (temperature limits, pressure shutdowns, emergency stops), the AI should recommend configuring interlocks in the Safety tab rather than implementing safety logic in a script.

## Example Prompt

After copying your AI context, paste it into your AI along with `AI_Script_Generation_Guide.md` and add your request. Here's a complete example:

---

**You:** *[paste AI context JSON here]*

I need a script that:
- Calculates thermal efficiency from the hot-side and cold-side temperature drops and flow rates
- Publishes the efficiency as a percentage and the heat transfer rate in kW
- Logs a warning to the console if efficiency drops below 70%
- Uses a SignalFilter to smooth the efficiency value (tau=10s)

Also, my hot-side outlet has a max design temperature of 180 degC. Should I add any safety interlocks for that?

---

The AI will generate the script using your exact channel names from the context, and should recommend adding an interlock (e.g., HIHI alarm at 175 degC with a `set_output` action to close the hot-side isolation valve) rather than putting temperature protection in the script.
