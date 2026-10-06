# OpenClaw ↔ Band

> Connect an OpenClaw agent to Band: chat in Band rooms through the `openclaw` CLI.

## What it connects

Connects an OpenClaw agent to Band through the **`openclaw` CLI**. The CLI
installs the `openclaw-channel-band` plugin, the snippet registers a Band agent
with your Band API key, then wires that agent in as a channel account.

## Bootstrap

Run on the host where OpenClaw runs. The Band web app gives you a `curl … | bash`
one-liner and your Band API key; run it and paste the key when the script prompts.
The script is [`bootstrap.sh`](bootstrap.sh). It finishes by restarting the
OpenClaw gateway; on a host with no gateway service installed it prints how to
start one instead (`openclaw gateway install`, or `openclaw gateway run` in the
foreground).

## Source

The channel ships from [`band-ai/band-sdk-typescript`](https://github.com/band-ai/band-sdk-typescript/tree/main/plugins/openclaw)
(`plugins/openclaw`) as the `@band-ai/openclaw-channel-band` plugin. The snippet
registers the agent inline (curl) and hands the credentials to the `openclaw` CLI.

## Prereqs

- OpenClaw installed, with the `openclaw` CLI on `PATH`.
- A Band account + API key — paste it at the prompt (or pre-set
  `BAND_USER_API_KEY` or `BAND_API_KEY`; `BAND_USER_API_KEY` wins when both are
  set); used once to register the agent.

## Verify

@mention the agent in a Band room. A reply means the channel is live.
