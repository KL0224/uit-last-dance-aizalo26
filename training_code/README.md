# Training Code & Model Declarations - DataMate 2026
Team: UIT Last Dance (zaic2026_datamate_uit_last_dance:final)

## 1. Training Status & Strategy Declaration
Per Section 8 of the Zalo AI Challenge 2026 Docker Submission Guide:
- **Training Method**: In this solution, the team relies on a structured **Agentic Ingestion, Grounding, Text-to-SQL Planning, Execution Sandbox, and Proof-Driven Risk-Gate** architecture.
- **Base Model**: Pretrained open-source foundational LLM `Qwen/Qwen3.5-9B` (and fallback `Qwen/Qwen2.5-3B` for semantic grounding).
- **Fine-Tuning**: No fine-tuning on public or private test sets was performed (Rule 6 compliance). Model weights utilized are unmodified open-source base checkpoints released prior to 26 October 2026 under the Apache 2.0 license.

## 2. Directory Structure
```
training_code/
├── README.md              # This declaration and documentation
├── requirements.txt       # Pinned training/fine-tuning dependencies
├── train.sh               # Training entry point script
├── data_manifest.json     # Manifest of public base models, SHA-256 and dataset splits
├── configs/               # Hyperparameter and model configuration files
├── src/                   # Training and data processing source code
├── data_generation/       # Data synthesis and preprocessing scripts
├── data/                  # Provided train/val data references
├── logs/                  # Training execution logs
└── checkpoints/           # Training verification checkpoints
```

## 3. Reproduction & Execution
If fine-tuning or evaluation is triggered:
```bash
bash /code/training_code/train.sh
```
