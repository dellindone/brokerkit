---
title: Project Vision
chapter: 1
volume: Volume I - Software Architecture
version: 1.0
status: Draft
author: BrokerKit Engineering Handbook
---

# Chapter 1 — Project Vision

> "A good architecture allows the system to evolve without forcing every consumer to change."

---

# Learning Objectives

By the end of this chapter you will understand:

- Why BrokerKit exists
- Problems with existing broker SDKs
- The philosophy behind a broker-agnostic architecture
- The long-term goals of the project
- The engineering principles that guide every design decision
- Why AI integration should be separated from broker implementations
- The scope of BrokerKit
- What BrokerKit is **not**

---

# 1. Introduction

Modern algorithmic trading applications are becoming increasingly sophisticated.

A trading application is no longer a script that places a buy order after a moving average crossover.

Today, trading systems may include:

- Real-time market data processing
- Historical data analysis
- Risk management
- Portfolio management
- AI-powered decision making
- Autonomous agents
- Notification systems
- Backtesting engines
- Paper trading
- Multiple broker integrations

As the complexity of these systems increases, the limitations of broker-specific SDKs become more apparent.

Most broker SDKs are designed to expose an API—not to provide a reusable software architecture.

This distinction is important.

A broker SDK solves the problem:

> "How do I communicate with Broker X?"

BrokerKit aims to solve a different problem:

> "How do I build a trading application that is independent of any broker?"

---

# 2. Problem Statement

Suppose you start building a trading application using the Groww SDK.

Your code might look something like this:

```python
client = GrowwClient(...)

quote = client.get_quote(...)

order = client.place_order(...)
```

Initially, this feels simple and productive.

However, after a few months, new requirements emerge:

- Your broker increases API pricing.
- Certain instruments are unavailable.
- You need features only another broker offers.
- Your users request support for additional brokers.
- You want to paper trade using a simulator.
- You want to run integration tests without hitting live APIs.

At this point, every part of the application depends on Groww-specific code.

Replacing the broker becomes a large and risky refactoring effort.

This is a textbook example of **tight coupling**.

The business logic is no longer independent.

Instead, it is deeply intertwined with implementation details.

---

# 3. Why Existing SDKs Are Not Enough

Most official broker SDKs are designed with one primary objective:

> Provide access to a broker's REST and WebSocket APIs.

This is perfectly reasonable.

It is not the responsibility of a broker SDK to solve architectural problems for your application.

However, from the perspective of an application developer, several challenges arise.

## 3.1 Vendor Lock-In

Applications become tightly coupled to one broker.

Changing brokers often requires modifying:

- Order placement logic
- Authentication
- Portfolio handling
- Historical data retrieval
- Streaming
- Error handling

The larger the codebase becomes, the harder migration becomes.

---

## 3.2 Different Data Models

Every broker exposes slightly different payloads.

Example:

Broker A

```json
{
    "ltp": 2450.25
}
```

Broker B

```json
{
    "last_price": 2450.25
}
```

Broker C

```json
{
    "price": 2450.25
}
```

Although these values represent the same concept, every application must write conversion logic.

As more brokers are added, this duplication grows.

---

## 3.3 Authentication Differences

Every broker authenticates differently.

Some use OAuth.

Some use API keys.

Some require browser login.

Some require TOTP.

Some use refresh tokens.

Without a common abstraction, authentication logic leaks throughout the application.

---

## 3.4 Different Error Models

Every broker reports failures differently.

One broker may return:

```text
401 Unauthorized
```

Another may return:

```text
Invalid Session
```

Another:

```text
Token Expired
```

From the application's perspective, these all represent the same problem:

> The current session is no longer valid.

BrokerKit will normalize these differences into a consistent exception model.

---

# 4. Vision

BrokerKit aims to become the standard broker abstraction library for Python.

Applications should communicate with a single interface regardless of the underlying broker.

The desired architecture is:

```
Trading Application
        │
        ▼
BrokerKit
        │
        ▼
Broker Adapter
        │
        ▼
Broker API
```

This simple separation allows applications to evolve independently of broker implementations.

---

# 5. Core Philosophy

BrokerKit is built around one central idea:

> Business logic should never depend on broker implementations.

Instead:

- Applications depend on abstractions.
- Broker implementations depend on those abstractions.
- New brokers are added without modifying application code.

This philosophy follows the Dependency Inversion Principle (DIP), one of the five SOLID principles.

The rest of this handbook will build on this foundation.