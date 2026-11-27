Existing solutions:
RAG



- Policy engines: [Open Policy Agent (OPA)](https://www.openpolicyagent.org/docs)
- Vector-store authorization: 
[Qdrant](https://qdrant.tech/documentation/search/filtering/): supports filtering vector searches using structured payload fields
[Weaviate](https://docs.weaviate.io/weaviate/configuration/rbac): offers role-based access control and resource-level permissions
 - Content detection and redaction: Microsoft [Presidio](https://presidio.dataprivacystack.org/text_anonymization/)
 - Managed DLP: Google Sensitive Data Protection, AWS Comprehend and Nightfall
 [Google Cloud Sensitive Data Protection](https://docs.cloud.google.com/sensitive-data-protection/docs/deidentify-sensitive-data)
 [Amazon Comprehend](https://docs.aws.amazon.com/comprehend/latest/dg/pii.html)
 [Nightfall](https://help.nightfall.ai/developer-api/nightfall_apis/dlp)
- Enterprise governance: [Microsoft Purview](https://learn.microsoft.com/en-us/purview/dlp-microsoft365-copilot-location-learn-about)


Strategy:
- Filter before RAG return information.
- Audit data shared to assess if information supposed to be filtered may be reconstructed from cumulative data shared.





Glosary:
PII entity: entity representing Personally Identifiable Information (PII): information that can identify a specific individual, either directly or indirectly.
DLP - Data Loss Prevention: security discipline concerned with preventing sensitive information from being exposed, leaked or transferred to unauthorized parties.
IFC - Information-Flow Control: security mechanism that tracks where information comes from, how it propagates, and where it is allowed to go.
Capability systems: capability-based security is an authorization model in which an agent receives explicit, narrowly scoped permissions to access resources or perform actions.

Sources:
[Patrick Lewis et Al, *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*, NeurIPS 2020, 12 Apr 2021](https://arxiv.org/abs/2005.11401)
[Haoran Wang et Al, *Privacy-Aware Decoding: Mitigating Privacy Leakage of Large Language Models in Retrieval-Augmented Generation*, , 05 Aug 2025](https://arxiv.org/html/2508.03098v1)
[Tingting Tang et Al, *Differentially Private Retrieval-Augmented Generation*, , 16 Feb 2026](https://arxiv.org/abs/2602.14374)
[Yuandao Cai et Al, *Ghost in the Agent: Redefining Information Flow Tracking for LLM Agents*, , 16 Feb 2026](https://arxiv.org/html/2604.23374v1)
[Saleh Almohaimeed et Al, *Privacy-Preserving RAG by Concealing Sensitive Information from External LLMs*, , 5 Sep 2026](https://arxiv.org/abs/2608.12675)
[Andreea-Elena Bodea et Al, *SoK: Privacy Risks and Mitigations in Retrieval-Augmented Generation Systems*, SaTML 2026, 7 Jan 2026](https://arxiv.org/abs/2601.03979)
[Yuming Xu et Al, *A Survey of Secure Retrieval-Augmented Generation*, , 12 Oct 2026](https://arxiv.org/html/2604.08304)
[Yanming Mu et Al, *Towards Secure Retrieval-Augmented Generation: A Comprehensive Review of Threats, Defenses and Benchmarks*, , 23 Mar 2026](https://arxiv.org/pdf/2603.21654)
[Daniel Kifer et Al, *Pufferfish: A Framework for Mathematical Privacy Definitions*, ACM Transactions on Database Systems (TODS), 06 Jan 2014](https://users.cs.duke.edu/~ashwin/pubs/pufferfish_TODS.pdf)

OpenAI:
[Orchestration and handoffs](https://developers.openai.com/api/docs/guides/agents/orchestration)
[Running agents](https://developers.openai.com/api/docs/guides/agents/running-agents)
[Building agents](https://developers.openai.com/tracks/building-agents)
[Agents](https://openai.github.io/openai-agents-python/agents/)

Anthropic:
[Equipping agents for the real world with Agent Skills](https://www.anthropic.com/research/equipping-agents-for-the-real-world-with-agent-skills)
[Agent Skills](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
[Building effective agents](https://www.anthropic.com/research/building-effective-agents)
[Trustworthy agents in practice](https://www.anthropic.com/research/trustworthy-agents)

Microsoft:
[Information-flow control: Moving toward secure, autonomous agents](https://commandline.microsoft.com/information-flow-control-moving-toward-secure-autonomous-agents/)
[Securing AI Agents with Information-Flow Control](https://www.microsoft.com/en-us/research/publication/securing-ai-agents-with-information-flow-control/)

