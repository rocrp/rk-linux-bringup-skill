# rk-linux-bringup-skill

**A Linux bring-up skill for Rockchip (RK3399 / RK356x / RK3588) boards:
an AI agent and you take an old board that only runs its stock firmware
and bring it up on Armbian / mainline Linux, stage by stage.**

[中文](README.md) · [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) · MIT

---

## Background

**The fun of embedded DIY** is rescuing obsolete hardware cheaply: face-scanning terminals,
advertising players, TV boxes, cloud-desktop boards… A few dozen to a few hundred yuan each, and
the hardware is often far better than a dev board at the same price. The classic uses are TV boxes,
software routers, NAS boxes and small servers.

The software side already has a mature open-source ecosystem: **Armbian** provides generic ARM
distributions and an image framework, **OpenWrt** does routing, and domestic NAS systems such as
**fnOS (飞牛 OS)** are filling in the rest. Together these purpose-built Linux distributions have
built a huge DIY community.

But between the board in someone's hands and being able to run these systems, there is one more
layer:

> **Every vendor is different, the design is never published, and the vendor ships only Android or
> a closed Linux. If you want to run a general-purpose Linux, you have to bring up the device tree
> (dtb) yourself.**

Not every DIY hobbyist has the background to solve the problems along the way: decompiling DTBs,
writing DTS, reading boot logs, packaging images, and patiently flashing and retrying over and over
again.

Held back by that barrier, many players can only hope that some expert happens to have ported their
exact board already. A lot of that hope stalls right there…
**…until AI agents arrived.**

An AI agent is the strongest developer, the strongest architect, the most professional expert and the
most well-read reference of our time. It is good at reading massive logs, decompiling binaries,
diffing device trees, looking up kernel bindings, and writing scripts and docs — exactly the most
time-consuming parts of a port. And the human still holds what the agent does not have: hands, eyes,
a multimeter, and the judgement of whether this board is worth rescuing.

**What this repository does** is turn that human–machine collaboration into a reusable procedure:
**an agent skill**, plus generic tools, document templates and a collaboration protocol. Hopefully
it lowers the technical barrier to playing with boards and opens up more possibilities.

## Why Rockchip?

So far, board vendors using RK-series chips almost never lock anything down, which makes these boards
very valuable for reuse. On the other side, RK's MASKROM mode means that even a badly flashed U-Boot
can be recovered. In other words, RK boards are the ones you "almost never have to worry about
bricking" — unless the eMMC itself is damaged.

[The ophub repository](https://github.com/ophub/amlogic-s9xxx-armbian) covers three vendors: Rockchip (瑞芯微), Amlogic (晶晨) and Allwinner (全志).
I only know RK well so far, so this repository supports Rockchip chips. Other vendors may be
supported later, or may not.

## What it solves

Most RK porting material out there is *a conclusion about one board*: one dts, one issue, one image.
Swap in another board and those conclusions are almost useless.

What this repository provides is the **process**:

- what to ask and measure first when you get a completely unknown board;
- how to dig the device tree, partition table and pin information out of the stock system;
- how to get a mainline kernel running without writing to eMMC;
- how to bring up one peripheral at a time, each step with a verifiable acceptance criterion;
- how to package the result into an image, verify cold boots, and finally turn it into a dts that
  upstream will accept.

It does not port the board for you, but it makes the agent know **what to do next, what counts as
done, and when it must stop and ask you**.

## Requirements

| Requirement | Notes |
|---|---|
| **Rockchip SoC** | RK3399 / RK356x / RK3588 etc., with mainline SoC support |
| **Working board** | powers on, reaches the stock system (MaskROM at the very least) |
| **Stock system intact** | it is the primary evidence source; wiping it makes life very hard |
| **TTL serial** | already exposed or solderable — this is your only pair of eyes |
| **MaskROM access** | button location plus the matching USB port; this is the rescue path |
| **Backup capability** | a backup disk, a way to read flash, and a way to flash it back |

Missing serial or missing backup, better not to start: every later step turns into a change you
cannot see.

## Usage

### 1. Install an agent

Claude Code, Codex, Cursor, Gemini CLI, DeepSeek Harness and so on all work. This skill only relies
on basics such as "can read and write files, can run commands".

### 2. Install the skill

The cross-tool location is `~/.agents/skills/`:

```bash
git clone https://github.com/weixr18/rk-linux-bringup-skill.git \
  ~/.agents/skills/rk-linux-bringup-skill
```

Other locations (pick any one):

| Tool | Location |
|---|---|
| Claude Code | `~/.claude/skills/rk-linux-bringup-skill/` or a project-local `.claude/skills/` |
| DeepSeek Harness | `~/.dsh/skills/`, `~/.agents/skills/` or a project-local `.dsh/skills/` |
| Shared in a project | `<project>/.agents/skills/rk-linux-bringup-skill/` |

After installing, `rk-linux-bringup-skill` should appear in the agent's skill list.

### 3. Wire up four things

| Connection | Purpose |
|---|---|
| **USB** | flashing / MaskROM (also the power supply on some boards) |
| **Serial** | boot log and login shell; mind the levels (TTL or RS-232) |
| **Ethernet** | same subnet as your workstation, for SSH and TFTP |
| **HDMI** | second pair of eyes; watch the screen (a USB capture dongle helps) |

### 4. Start the interactive bring-up

Open an agent in a fresh directory and say:

> I want to bring up Linux on this RK board. The model is …, the stock system is …, serial is on COMx.

Then answer its intake questions. It will first have you fill in facts and confirm a rollback path,
then move into P0.

**Suggested rhythm**: advance one small phase per session; before ending, have it write a log and
update the progress page. The next session only needs three things to start: the plan, the progress
page, and the previous log.

## Workflow

```
P0 scope ──► P1 evidence ──► P2 observability ──► P3 boot ──► P4 peripherals ──► P5 image ──► P6 upstream
   │             │                │                 │             │                │
 rollback       facts            eyes             kernel         dtb             image
   G0            G1               G2                G3            G4               G5          G6
```

| Phase | In one sentence | Gate |
|---|---|---|
| **P0 Scope** | decide whether and how far | can reflash, can rescue, scope frozen |
| **P1 Evidence** | turn unknowns into knowns | every key fact has a source; backup verified |
| **P2 Observability** | build two independent pairs of eyes | capture everything from the first DDR line to `login:` |
| **P3 Boot** | mainline kernel on a zero-write medium | serial + power + storage + Ethernet probes pass |
| **P4 Peripherals** | one class at a time, in dependency order | core set passes; dts frozen |
| **P5 Image** | reproducible and deliverable | 3/3 cold boots with power removed |
| **P6 Upstream** | let others use it (optional) | PR merged, or explicitly declined |

What actually takes the time is not writing DTS but **evidence, observability and packaging**.
Writing DTS is often only a fifth of the whole schedule.

## Workspace and documents

**One board, one directory.** Never share one workspace between boards. The directory always holds
four things:

```
<board>-bringup/
├── board-profile.md    # source of facts: where this chip / this pin was observed
├── feasibility.md      # can it be done, how far, what is explicitly out of scope
├── plan.md             # what to do: phases, gates, how to back out of a failure
├── progress.md         # where we are: one sentence + one line per sub-phase + log index
└── logs/
    └── session-01-P0.md  # what actually happened: commands, results, evidence, leftovers
```

The rules are simple, but they matter:

| Document | Rule |
|---|---|
| **Feasibility** | finished in one pass at P0, with an explicit go / conditional go / no-go |
| **Plan** | draft first; once you confirm it, finalize and **freeze**; later changes must be proposed or approved by you, with a revision record |
| **Progress** | only "where we are" and per-sub-phase status, **no detail**; dig into the session log for that |
| **Session log** | one per conversation, zero-padded number; details live only here; finished logs are append-only |

The payoff: change agent, change day, change handover person — open the directory and you know
"what this board is, how we plan to do it, where we are, what has been done" without scrolling chat
history.

For the skeleton, naming and kickoff checklist see [`templates/workspace-layout.md`](templates/workspace-layout.md);
for the full rules see [`references/13-workspace.md`](references/13-workspace.md).

## How it works

**What is a dtb?** The ARM world has no ACPI/PCI auto-enumeration like x86. Which peripherals a
board has, which pins they sit on, which clocks they use and which regulator feeds them are all
described by a binary **device tree blob (dtb)**; the kernel reads it to discover hardware and bind
drivers.

**Why is that painful?** Every board is routed differently, so a dtb is inherently non-portable. The
vendor only ships a compiled dtb, never the sources; and mainline needs a different dtb, written
against its own bindings.

**dts and dtc**: dts is the text source, dtc compiles it into a dtb and can also decompile a dtb
back into dts. The day-to-day work of a port is reading the vendor dtb, writing your own dts,
compiling, deploying and verifying.

**In one sentence:**

> Pull as much information as possible out of the stock system over serial, have the AI generate
> dts nodes peripheral by peripheral, verify availability step by step, then integrate everything
> into a working image and flash it — and share it with the open-source community.

## Provenance

The method comes from three real RK board ports (two classes: RK3399 and RK3568). Device
information, verification records and known limitations from those ports are public in three ophub
issues: [#3722](https://github.com/ophub/amlogic-s9xxx-armbian/issues/3722),
[#3725](https://github.com/ophub/amlogic-s9xxx-armbian/issues/3725),
[#3762](https://github.com/ophub/amlogic-s9xxx-armbian/issues/3762).

This repository keeps only the method; it contains no board-specific dts, images or logs.

## Repository layout

```
SKILL.md             agent entry: phases, gates, stop points, red lines, navigation
references/          14 documents: phase machine, intake, evidence, observability, boot, dts,
                     peripherals, image, upstream, troubleshooting, pitfalls, collaboration,
                     branch C, workspace
templates/           9 templates: board profile, feasibility, plan, progress, session log,
                     change notes, release notes, project rules, workspace layout
scripts/             15 generic scripts: dtb inspect/edit/semantic diff, serial, TFTP,
                     acceptance probes, image assembly
assets/              three diagrams: phase flow, boot chain, wiring
```

## FAQ

**No serial port?** Find a test point, solder a header, or pick another board. Serial is the only
place the boot process is visible; without it you can only guess.

**No TF card slot?** Use TFTP in-memory boot or a USB rootfs; nothing is written to eMMC the whole
way. See `references/04-boot.md`.

**Stock system already wiped / never backed up?** Try brick recovery first (MaskROM + vendor
firmware). If that fails, you have to derive everything from the generic SoC design, which is much
harder.

**Must it be Armbian?** No. The method is distribution-agnostic; the image-assembly chapter uses
Armbian as the example because its `fdtfile` mechanism is the least work.

**Can it brick the board?** With a backup and a MaskROM path it is usually recoverable — but not
guaranteed. Before the first eMMC write, make sure the backup is readable.

**What skill level is needed?** Wiring, reading serial output and using a multimeter is enough. The
agent walks you through DTS step by step.

**Does it support 32-bit ARM?** This skill targets arm64 RK3399 / RK356x / RK3588. The approach for
32-bit platforms is the same, but images and toolchain have to be set up separately.

## Limitations

- **No new drivers**: anything mainline lacks goes on the "won't do" list, it is not developed on the
  bring-up bench.
- **No building your own U-Boot/kernel**: only an entry note (`references/12-branch-c.md`), no
  operations manual.
- **No guarantee of success**: board batches, vendor firmware and mainline support all affect the
  outcome.
- **Hardware can be damaged**: wrong power-enable or GPIO polarity really does burn boards. Any
  change touching power must be reviewed by a human.
- **Not a substitute for professional repair**: soldering, desoldering and BGA rework belong with
  someone who does it for a living.

## Contributing

Fixes, pitfalls and generic tools are welcome. Board-specific dts should go to
[ophub](https://github.com/ophub/amlogic-s9xxx-armbian) or the corresponding kernel tree.
Details in [CONTRIBUTING.md](CONTRIBUTING.md).

## License and acknowledgements

MIT. See [LICENSE](LICENSE).

The method took shape from public community material and discussion; special thanks to
[ophub](https://github.com/ophub/amlogic-s9xxx-armbian), [Armbian](https://www.armbian.com/) and the
Rockchip mainline kernel maintainers.
