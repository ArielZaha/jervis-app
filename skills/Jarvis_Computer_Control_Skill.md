# Jarvis Computer Control Skill

## Purpose

You are an implementation agent working on **Jarvis**, a personal AI voice/chat assistant.

This skill defines a computer-control capability where the user can tell Jarvis:

> "Take control of my computer and [command]."

Jarvis should then visibly control the user's computer using the mouse and keyboard, while the user watches everything happen on screen.

The defining product requirement is:

**Jarvis must actually operate the computer, not merely describe what it would do.**

For example, if the user says:

> "Take control of my computer and play Bohemian Rhapsody on Spotify."

Jarvis should visibly:

1. Take control of the mouse/keyboard.
2. Move the cursor to Spotify.
3. Open Spotify if necessary.
4. Wait for Spotify to finish opening.
5. Locate the Spotify search field.
6. Click the search field.
7. Type the requested search term visibly, character by character or using normal keyboard input.
8. Wait for search results.
9. Identify the requested song.
10. Move the cursor to the correct result.
11. Click its play button or otherwise start playback.
12. Verify that the requested action actually happened.
13. Give the user a concise completion message.

The user should be able to watch the entire process.

---

# Core Product Principle

Jarvis is not simply an API assistant in this mode.

It is a **visible computer-use agent**.

The user should be able to see:

```text
Jarvis decides what to do
        ↓
Jarvis moves the mouse
        ↓
Jarvis interacts with the visible UI
        ↓
Jarvis waits for the UI
        ↓
Jarvis continues
        ↓
Jarvis verifies the result
```

Do not hide the important actions from the user.

Do not instantly open URLs or call backend APIs when the requested behavior specifically requires visible computer interaction.

If the user says:

> "Take control of my computer and open Spotify."

the expected behavior is that the user sees Jarvis open Spotify.

If the user says:

> "Take control of my computer and search Spotify for Radiohead."

the expected behavior is that the user sees the cursor go to Spotify, the search field get selected, and "Radiohead" get entered.

---

# Trigger Phrase

Computer-control mode should activate when the user explicitly requests it.

Examples:

```text
Take control of my computer and open Spotify.
```

```text
Take control of my computer and play Bohemian Rhapsody.
```

```text
Take control of my computer and open Chrome and search for Minecraft.
```

```text
Take control of my computer and go to YouTube and play a video.
```

```text
Take control of my computer and open VS Code.
```

Equivalent natural wording can also be supported:

```text
Jarvis, control my computer and...
Take over my computer and...
Use my computer and...
Control the mouse and...
Operate my computer and...
```

However, normal Jarvis commands should not automatically enter full computer-control mode unless the user has explicitly enabled or requested that capability.

---

# Explicit User Intent

Computer control is a powerful capability.

The assistant must distinguish between:

```text
"How do I open Spotify?"
```

and:

```text
"Take control of my computer and open Spotify."
```

The first asks for instructions.

The second requests actual computer control.

Only the second should trigger computer-use automation.

---

# Human-Visible Interaction

The most important requirement is that actions happen visibly.

When Jarvis performs an action, the user should be able to observe:

- Mouse movement
- Mouse clicks
- Keyboard input
- Application opening
- Windows changing
- Pages loading
- Search results appearing
- Buttons being clicked
- Playback starting
- Menus opening

Do not make the computer appear frozen while Jarvis secretly performs everything through hidden APIs.

---

# Mouse Movement

The mouse cursor should physically move to the target.

For example:

```text
Current position
      ↓
Move toward Spotify
      ↓
Hover over Spotify
      ↓
Click
```

Avoid instantly teleporting the cursor unless the chosen computer-control framework inherently does so and there is no practical alternative.

Smooth or human-readable movement is preferred.

The exact animation speed can be configurable.

Example configuration:

```python
MOUSE_MOVE_DURATION = 0.35
```

For complicated actions, the movement can be slower.

---

# Keyboard Input

When typing into an application, the user should see the input happen.

For example:

```text
B
Bo
Boe
Bohe
Bohem
...
```

The implementation may use normal keyboard automation rather than literally sleeping between every individual character, but the result should remain visibly understandable.

Optional configurable setting:

```python
TYPING_DELAY = 0.02
```

For normal text:

```text
Bohemian Rhapsody
```

For sensitive fields such as passwords, do not reveal or record the contents.

---

# Waiting for Applications

Never assume an application opened instantly.

Bad:

```python
open_spotify()
click_search()
```

Better:

```text
Open Spotify
↓
Wait until Spotify window appears
↓
Verify Spotify is ready
↓
Find search field
↓
Continue
```

The computer-control system should wait for observable UI state.

Use:

- Window detection
- Accessibility/UI-tree state
- Image recognition
- OCR
- Application process state
- Explicit UI readiness checks

depending on what the chosen framework supports.

Avoid relying only on arbitrary long sleeps.

---

# State-Based Automation

Prefer:

```text
WAIT UNTIL condition is true
```

over:

```text
SLEEP 5 SECONDS
```

Example:

```python
wait_until(
    lambda: spotify_window_exists(),
    timeout=15
)
```

Then:

```python
wait_until(
    lambda: spotify_search_field_visible(),
    timeout=10
)
```

Then:

```python
click(search_field)
```

This makes Jarvis much more reliable across computers with different performance.

---

# Computer-Control Loop

The implementation should follow an observe → decide → act → verify loop.

Conceptually:

```text
OBSERVE
  ↓
DECIDE
  ↓
ACT
  ↓
OBSERVE
  ↓
VERIFY
  ↓
CONTINUE OR RECOVER
```

Example:

```text
Observe:
Spotify is not open.

Decide:
Open Spotify.

Act:
Click Spotify in Applications / Dock / Start Menu.

Observe:
Spotify window appears.

Decide:
Find search field.

Act:
Move cursor to search field and click.

Observe:
Search field is focused.

Act:
Type "Bohemian Rhapsody".

Observe:
Search results appear.

Act:
Click play.

Observe:
Playback begins.

Verify:
Song title and playback state match the request.
```

---

# Planning

Before taking control, convert the user's request into a task plan.

Example:

User:

> Take control of my computer and play Bohemian Rhapsody on Spotify.

Internal plan:

```json
{
  "goal": "Play Bohemian Rhapsody on Spotify",
  "steps": [
    "Locate Spotify",
    "Open Spotify if necessary",
    "Wait for Spotify",
    "Find search field",
    "Search for Bohemian Rhapsody",
    "Wait for results",
    "Identify correct song",
    "Click play",
    "Verify playback"
  ]
}
```

The plan should be dynamic.

Do not blindly execute steps if the UI is different from what was expected.

---

# Adapt to the Actual UI

The computer may not look exactly as expected.

Possible differences:

- Spotify is already open.
- Spotify is minimized.
- Spotify is maximized.
- Spotify is on another monitor.
- The user has a different theme.
- A login screen appears.
- A popup appears.
- A notification covers the interface.
- A browser has a different layout.
- An application takes longer to load.

Jarvis should observe the current state and adapt.

Do not assume fixed coordinates are always correct.

---

# Avoid Fragile Fixed Coordinates

Bad:

```python
click(540, 82)
```

because the target may move.

Prefer:

- Accessibility identifiers
- UI element names
- DOM selectors when controlling a browser
- OCR
- Computer vision
- Window-relative coordinates
- Image/template matching
- Application-specific accessibility APIs

If coordinates are unavoidable, calculate them relative to the current window or screen state whenever possible.

---

# Browser Control

When controlling a browser, Jarvis should interact with the actual visible browser.

For example:

```text
Open Chrome
↓
Wait for Chrome
↓
Click address bar
↓
Type the URL
↓
Press Enter
↓
Wait for page
↓
Observe page
↓
Click requested element
```

If browser automation is used, keep the browser visible.

Do not silently perform the action in a separate hidden browser if the user's request is explicitly for visible control.

---

# Application Control

Jarvis should be able to interact with desktop applications when supported by the chosen computer-control framework.

Examples:

- Spotify
- Chrome
- Safari
- VS Code
- Finder
- System Settings
- Discord
- File managers
- Other normal desktop applications

The exact supported application set depends on the operating system and automation framework.

Do not claim support for an application that the implementation cannot actually control.

---

# Cross-Platform Design

Jarvis may eventually support:

- macOS
- Windows
- Linux

Do not hard-code the entire computer-control system around macOS.

Use an abstraction:

```python
computer_controller.py
```

with platform-specific implementations:

```text
computer/
    base.py
    macos.py
    windows.py
    linux.py
```

Conceptually:

```python
controller.open_application("Spotify")
controller.move_mouse(x, y)
controller.click()
controller.type_text("Bohemian Rhapsody")
controller.press("enter")
controller.screenshot()
```

The exact implementation depends on the selected framework.

---

# Recommended Architecture

Use a dedicated computer-control service.

Example:

```text
Jarvis
│
├── Voice Input
├── Chat Input
├── LLM / Intent Router
│
├── Computer Control Service
│   ├── Planner
│   ├── Computer Controller
│   ├── Vision / UI Detection
│   ├── Action Executor
│   ├── State Observer
│   ├── Verification
│   └── Safety Manager
│
└── Existing Services
    ├── Spotify
    ├── YouTube
    └── Other integrations
```

Do not put raw mouse-control code throughout `app.py`.

Create a clean interface.

---

# Suggested Computer Controller API

Conceptually:

```python
class ComputerController:

    def screenshot(self):
        ...

    def move_mouse(self, x, y, duration=0.3):
        ...

    def click(self, button="left"):
        ...

    def double_click(self):
        ...

    def type_text(self, text, interval=0.02):
        ...

    def press(self, key):
        ...

    def hotkey(self, *keys):
        ...

    def open_application(self, name):
        ...

    def wait_for(self, condition, timeout=15):
        ...

    def get_active_window(self):
        ...

    def find_element(self, description):
        ...

    def scroll(self, amount):
        ...
```

The actual API may differ depending on the selected implementation framework.

---

# Observation System

Jarvis needs a way to understand what is currently visible.

Possible observation sources:

## Screenshots

Take screenshots of the current screen.

Useful for:

- Buttons
- Icons
- Layout
- Visual verification

## OCR

Useful for:

- Search fields
- Text labels
- Error messages
- Song names
- Website content

## Accessibility/UI tree

Prefer this when available.

It can provide:

- Buttons
- Text fields
- Window names
- Roles
- Labels
- Focus state

Accessibility information is generally more reliable than pure image coordinates.

## Browser DOM

For browser pages, DOM-based detection can be highly reliable.

However, if the user explicitly wants to see visible interaction, still perform the visible interaction in the actual browser.

---

# Action Verification

Every important action should be verified.

Example:

```text
Action:
Click Spotify.

Verification:
Spotify window appeared.
```

Example:

```text
Action:
Type "Bohemian Rhapsody".

Verification:
Search field contains the requested text.
```

Example:

```text
Action:
Click play.

Verification:
Playback state changed to playing.
```

Never assume a click worked merely because the click command executed.

---

# Recovery

If an action fails, Jarvis should recover when safe.

Example:

```text
Expected:
Spotify search field.

Observed:
Spotify home page.

Recovery:
Search for the search field again.
```

Another example:

```text
Expected:
Spotify window.

Observed:
Spotify login screen.

Recovery:
Stop and tell the user that Spotify needs to be logged in.
```

Do not blindly continue after the UI diverges from the expected state.

---

# Retry Policy

Use limited retries.

Example:

```text
Try action
↓
Verify
↓
If failed:
    re-observe
    retry once
↓
If still failed:
    explain failure
```

Do not create infinite loops.

A reasonable maximum should be configurable:

```python
MAX_ACTION_RETRIES = 2
```

---

# User Visibility

Jarvis should clearly communicate that it has taken control.

Example:

> Taking control of your computer.

Then perform the visible actions.

After completion:

> Done — Bohemian Rhapsody is playing on Spotify.

If the user interrupts:

> Stopping computer control.

Then immediately stop automated input.

---

# Emergency Stop

Computer control must have an immediate stop mechanism.

The user should be able to interrupt Jarvis using at least one reliable method.

Examples:

```text
"Stop"
"Jarvis stop"
"Release control"
"Cancel"
```

A physical emergency stop should also be considered, such as:

- A keyboard shortcut
- Moving the mouse to a configured corner
- A dedicated UI stop button

The emergency stop should take priority over normal task execution.

Example:

```text
Jarvis is clicking through a website
        ↓
User says "STOP"
        ↓
Automation stops immediately
```

Do not continue executing queued actions after the stop signal.

---

# User Control Has Priority

At all times, the user should be able to take the computer back.

If the user manually moves the mouse, types, or interacts with the computer while Jarvis is acting, the implementation should detect this where practical.

Possible policy:

```text
User interaction detected
        ↓
Pause Jarvis
        ↓
Tell user:
"I detected manual input. Pausing."
        ↓
Wait for user instruction or explicit resume
```

Do not fight the user for control of the mouse.

---

# Safety Boundaries

Computer control can affect real files, accounts, applications, and services.

The implementation must distinguish between ordinary reversible actions and high-impact actions.

Ordinary examples:

- Open Spotify
- Search Google
- Play a song
- Open VS Code
- Open a website
- Scroll
- Change a normal UI setting

Higher-impact examples:

- Delete files
- Empty Trash/Recycle Bin
- Send messages
- Send emails
- Purchase something
- Submit forms with significant consequences
- Change passwords
- Change security settings
- Install unknown software
- Upload private files
- Transfer money
- Make irreversible account changes

For high-impact or irreversible actions, require explicit confirmation immediately before the action unless the user has explicitly configured a trusted workflow that permits it.

Example:

> I’m ready to delete these files. Do you want me to continue?

Do not silently perform destructive actions because the user previously said "take control."

---

# Credentials and Sensitive Information

Never expose passwords, authentication tokens, API keys, private keys, or other secrets.

If a login page appears:

- Do not guess credentials.
- Do not reveal saved credentials.
- Do not transmit credentials to an unexpected website.
- If the user needs to enter a password, pause and let the user handle the sensitive field when appropriate.
- Do not log screenshots containing credentials.

If Jarvis can technically access a password manager, follow the user's explicit instructions and the password manager's security model rather than scraping or exposing stored secrets.

---

# Privacy

Computer control gives Jarvis access to whatever is visible on screen.

Treat screenshots and UI information as potentially private.

Do not:

- Store screenshots unnecessarily.
- Upload screenshots to external services without appropriate authorization.
- Include private screen content in logs.
- Send private content to the LLM when it is unnecessary for the task.

Only observe what is needed to complete the task.

---

# Screen Capture

If screenshots are used for vision:

1. Capture only when necessary.
2. Process locally when possible.
3. Avoid permanent storage.
4. Delete temporary screenshots after use.
5. Never log screenshots automatically.
6. Avoid capturing password managers, banking information, private chats, or other sensitive screens unless the task genuinely requires it and the user has authorized the operation.

---

# LLM Tool Design

Expose computer control as a structured tool.

Conceptually:

```json
{
  "name": "computer_control",
  "description": "Take visible control of the computer and perform the user's requested task.",
  "parameters": {
    "type": "object",
    "properties": {
      "task": {
        "type": "string"
      }
    },
    "required": ["task"]
  }
}
```

The exact schema must match Jarvis's existing LLM integration.

The LLM should provide the goal.

The computer-control agent should plan and execute the UI actions.

Do not allow the LLM to fabricate a claim such as:

```text
"The song is playing."
```

unless the computer-control system returned successful verification.

---

# Computer-Control Result

The computer-control service should return structured results.

Example success:

```python
ComputerTaskResult(
    success=True,
    task="Play Bohemian Rhapsody on Spotify",
    actions_completed=9,
    final_state="Spotify is playing Bohemian Rhapsody by Queen",
    error_code=None,
    error_message=None
)
```

Example failure:

```python
ComputerTaskResult(
    success=False,
    task="Play Bohemian Rhapsody on Spotify",
    actions_completed=4,
    final_state="Spotify login screen is visible",
    error_code="AUTH_REQUIRED",
    error_message="Spotify requires login before playback can continue."
)
```

The assistant's response should be generated from this result.

---

# Do Not Fake Actions

This is one of the most important rules.

Never respond:

> Done.

if Jarvis only planned the action.

Never respond:

> I opened Spotify.

if the Spotify window never appeared.

Never respond:

> The song is playing.

if Jarvis only searched for the song.

Never respond:

> I clicked the button.

if the click was not verified.

The computer-control layer must report the actual result.

---

# Example: Spotify

User:

> Take control of my computer and play Bohemian Rhapsody on Spotify.

Expected sequence:

```text
1. Detect Spotify.
2. If Spotify is closed:
      open Spotify.
3. Wait for Spotify window.
4. Observe Spotify UI.
5. Find search field.
6. Move mouse to search field.
7. Click search field.
8. Type:
      Bohemian Rhapsody
9. Wait for results.
10. Observe result list.
11. Identify:
      Bohemian Rhapsody — Queen
12. Move cursor to the correct play control.
13. Click.
14. Wait for playback state.
15. Verify the requested song is playing.
16. Return success.
```

Jarvis response:

> Done — Bohemian Rhapsody by Queen is now playing on Spotify.

If Spotify is not logged in:

> I opened Spotify, but it requires you to log in before I can play the song. I stopped there so you can log in.

---

# Example: YouTube

User:

> Take control of my computer and open YouTube and play a video about how black holes work.

Expected:

```text
Open browser
↓
Open YouTube
↓
Wait for YouTube
↓
Find search field
↓
Type search
↓
Submit
↓
Wait for results
↓
Identify an appropriate result
↓
Click result
↓
Wait for video
↓
Verify playback
```

Do not claim success merely because the YouTube page loaded.

---

# Example: VS Code

User:

> Take control of my computer and open VS Code.

Expected:

```text
Find VS Code
↓
Open VS Code
↓
Wait for window
↓
Verify VS Code is visible
```

Response:

> Done — VS Code is open.

---

# Example: Search

User:

> Take control of my computer and search Google for the best pizza recipes.

Expected:

```text
Open browser
↓
Navigate to Google
↓
Click search field
↓
Type query
↓
Submit
↓
Wait for results
↓
Verify results page
```

Response:

> Done — I searched Google for that.

---

# Long Tasks

For tasks containing multiple actions, Jarvis should keep going after each successful step.

Example:

> Take control of my computer, open Chrome, go to YouTube, search for Pink Floyd, and play the first result.

The task should be represented as:

```text
1. Open Chrome
2. Navigate to YouTube
3. Wait
4. Search Pink Floyd
5. Wait
6. Select first result
7. Start playback
8. Verify
```

If step 5 fails, do not pretend that step 6 happened.

---

# Progress Feedback

For long operations, Jarvis may provide short progress updates.

Example:

> Taking control.

Then:

> Opening Spotify.

Then:

> Searching for Bohemian Rhapsody.

Then:

> Starting playback.

Finally:

> Done — Bohemian Rhapsody is playing.

Do not flood the user with technical logs.

---

# Voice Feedback

Voice mode should remain natural.

Good:

> Taking control of your computer.

> Spotify is open. Searching now.

> Done — the song is playing.

Failure:

> I couldn't continue because Spotify is asking you to log in.

Avoid technical responses such as:

> UI element detection returned null.

Technical information belongs in developer logs.

---

# Chat Feedback

Chat can provide slightly more detail.

Example:

> I opened Spotify and found the requested song, but Spotify doesn't have an active playback device, so I couldn't start it.

---

# Focus and Accidental Input Prevention

Before typing:

1. Confirm the intended field is focused.
2. Do not type blindly.
3. If focus is uncertain, click the target field.
4. Verify the field contains the intended text when possible.

This prevents typing commands into the wrong application.

Example dangerous failure:

```text
Jarvis thinks Chrome search is focused
but VS Code is actually focused
↓
Jarvis types:
"Bohemian Rhapsody"
```

Avoid this through state verification.

---

# Window Management

Jarvis should understand:

- Current active application
- Current active window
- Minimized windows
- Multiple windows
- Multiple monitors
- Full-screen applications

Before interacting, ensure the intended application is active.

If a window is hidden/minimized, bring it to the foreground safely.

---

# Multiple Monitors

If multiple monitors exist:

- Determine which monitor contains the target window.
- Move the mouse to the correct screen.
- Avoid blindly assuming the primary display.

The user should be able to see the cursor move to the appropriate monitor.

---

# Failure Handling

Every computer-control operation should have a meaningful failure state.

## Application not found

> I couldn't find Spotify installed on this computer.

## Application failed to open

> I tried to open Spotify, but it didn't start.

## UI element not found

> I opened Spotify, but I couldn't find its search field. I stopped rather than clicking somewhere unsafe.

## Unexpected screen

> The page doesn't look like I expected, so I stopped instead of guessing.

## Timeout

> Spotify took too long to load, so I stopped the task.

## User interruption

> I detected that you took control of the mouse, so I paused.

## Permission issue

> macOS is blocking Jarvis from controlling the computer. You need to allow the required Accessibility/Automation permission.

Do not repeatedly retry a blocked OS permission.

---

# macOS Permissions

On macOS, visible mouse/keyboard automation may require permissions such as:

- Accessibility
- Automation
- Screen Recording, depending on the chosen observation method

The exact permissions depend on the implementation framework.

If permission is missing:

1. Detect the failure.
2. Explain which capability is unavailable.
3. Tell the user what permission needs to be enabled.
4. Do not claim computer control is working.

Never attempt to bypass macOS security permissions.

---

# Windows Permissions

On Windows, the implementation may require appropriate desktop/UI automation permissions depending on the framework.

Use supported Windows accessibility/UI automation APIs when possible.

Do not bypass Windows security mechanisms.

---

# Linux Permissions

On Linux, implementation details vary significantly by desktop environment and display server.

Support should be based on the actual environment.

Do not assume X11 behavior works under Wayland.

---

# Tool Selection

Before implementing, inspect the current Jarvis project and determine which computer-control technology is already available.

Possible approaches include:

- OS accessibility APIs
- PyAutoGUI
- Playwright for browser-specific control
- AppleScript / macOS Automation
- Windows UI Automation
- Accessibility frameworks
- Computer-use models
- Vision + mouse/keyboard automation

Do not add a large framework unnecessarily.

Choose the smallest reliable technology that satisfies the requirement.

For browser-only tasks, browser automation may be preferable.

For full desktop control, use an appropriate OS-level automation/accessibility system.

---

# Browser vs Desktop Strategy

Use the appropriate layer.

## Browser task

Example:

> Search Google for Python tutorials.

Prefer browser-aware automation when available.

## Desktop task

Example:

> Open Spotify and play a song.

Use desktop/UI automation.

## Mixed task

Example:

> Open Chrome, go to a website, download a file, and open it in VS Code.

Use both browser and desktop control as needed.

---

# Do Not Mix Hidden APIs With Visible Control Without Reason

If the user explicitly says:

> "Take control of my computer and do it so I can watch."

the visible UI interaction is part of the requested experience.

Do not replace the visible workflow with:

```text
Spotify API
→ play track
→ pretend mouse moved
```

That violates the intended behavior.

If an API is used internally for verification or metadata, that is fine, but the requested visible interaction should still happen when the task calls for it.

---

# Completion Criteria

A computer-control task is complete only when:

- [ ] The requested computer action was actually executed.
- [ ] The user could see the interaction.
- [ ] Each important step was observed/verified.
- [ ] Unexpected UI states were handled safely.
- [ ] Jarvis did not blindly click based on assumptions.
- [ ] Jarvis did not claim success before verification.
- [ ] The user can interrupt the task.
- [ ] Sensitive information was protected.
- [ ] Destructive/high-impact actions receive appropriate confirmation.
- [ ] Errors produce useful explanations.
- [ ] No infinite automation loop exists.

---

# Development Workflow

When asked to implement or fix computer control:

## Step 1 — Inspect

Read the existing Jarvis project.

Find:

- Main assistant file
- Voice input
- Chat input
- LLM/tool definitions
- Existing automation code
- Existing UI
- OS detection
- Permission handling
- Logging
- Existing Spotify/YouTube integrations

Do not rewrite the entire project without first understanding it.

## Step 2 — Identify Platform

Determine:

```text
macOS
Windows
Linux
```

Use platform-specific capabilities where necessary.

## Step 3 — Choose Control Layer

Determine whether the task requires:

```text
desktop automation
browser automation
accessibility API
vision
or a combination
```

## Step 4 — Build the Controller

Create a clean abstraction for:

```text
move
click
type
press
scroll
open
wait
observe
verify
stop
```

## Step 5 — Add Planning

Convert the user's goal into observable steps.

## Step 6 — Add Verification

Every important action must have a success condition.

## Step 7 — Add Recovery

Handle predictable UI differences without blindly guessing.

## Step 8 — Add Emergency Stop

Make interruption reliable before testing long tasks.

## Step 9 — Test

Test real visible workflows.

## Step 10 — Review

Check:

- Security
- Privacy
- Permissions
- Reliability
- User visibility
- Error handling
- Interruptibility
- Regression risk

---

# Testing Requirements

Test at minimum:

## Basic

```text
Take control of my computer and open Spotify.
```

## Search

```text
Take control of my computer and search Spotify for Radiohead.
```

## Playback

```text
Take control of my computer and play Bohemian Rhapsody on Spotify.
```

## Browser

```text
Take control of my computer and open YouTube.
```

## Multi-step

```text
Take control of my computer, open Chrome, go to YouTube, search for Pink Floyd, and play a result.
```

## Already-open application

Spotify/browser should not be unnecessarily reopened if it is already open and usable.

## Slow computer

The system should wait for UI state rather than failing immediately.

## Unexpected popup

The system should detect the unexpected state and either safely dismiss an expected popup or stop and ask the user.

## User interruption

Move the mouse manually or issue:

```text
Stop
```

Jarvis must stop.

## Missing permissions

Verify that Jarvis explains the permission problem.

## Wrong UI

Intentionally test a changed window/layout and make sure Jarvis does not blindly click.

---

# Final Implementation Principle

The computer-control feature should feel like the user has given Jarvis temporary control of their mouse and keyboard.

The user should be able to sit back and watch:

```text
"Take control of my computer and play Bohemian Rhapsody on Spotify."

             ↓

Jarvis takes control

             ↓

Mouse moves

             ↓

Spotify opens

             ↓

Jarvis waits

             ↓

Search field is clicked

             ↓

"Bohemian Rhapsody" is typed

             ↓

Results load

             ↓

Correct song is identified

             ↓

Play button is clicked

             ↓

Playback is verified

             ↓

Jarvis says:

"Done — Bohemian Rhapsody by Queen is playing."
```

That visible process is the feature.

Do not reduce it to an API call and a fake visual response.

The user must be able to see what Jarvis is doing, interrupt it when necessary, and understand why it stopped if something goes wrong.
