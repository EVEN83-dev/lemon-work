# -*- coding: utf-8 -*-
"""
Lemon Trainer — Lemon AI Engine 训练脚本
==========================================
基于 Unsloth + TRL 的 QLoRA 微调管线。

使用方式:
  python lemon_trainer.py --mode qlora --base_model Qwen/Qwen2.5-Coder-7B-Instruct

依赖:
  pip install unsloth trl datasets accelerate bitsandbytes peft

算力需求:
  - QLoRA 7B: RTX 3060 12GB (~8GB VRAM)
  - LoRA 7B:  RTX 4090 24GB (~20GB VRAM)
  - 全参 7B:  A100 40GB (~35GB VRAM)

参考:
  - Unsloth: https://github.com/unslothai/unsloth
  - Qwen2.5-Coder: https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct
  - TRL SFT: https://huggingface.co/docs/trl/sft_trainer
"""

import os
import json
import argparse
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field


# ============================================================
# 训练配置
# ============================================================

@dataclass
class LemonTrainConfig:
    """Lemon 训练配置"""
    # 模式
    mode: str = "qlora"  # qlora / lora / full

    # 模型
    base_model: str = "Qwen/Qwen2.5-Coder-7B-Instruct"
    output_dir: str = "./lemon-model-output"

    # LoRA 参数
    lora_r: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    lora_target_modules: List[str] = field(default_factory=lambda: [
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj",
    ])

    # QLoRA (4-bit)
    use_4bit: bool = True
    bnb_4bit_compute_dtype: str = "bfloat16"
    bnb_4bit_quant_type: str = "nf4"
    bnb_4bit_use_double_quant: bool = True

    # 训练超参数
    num_epochs: int = 3
    per_device_train_batch_size: int = 4
    gradient_accumulation_steps: int = 4
    learning_rate: float = 2e-4
    warmup_ratio: float = 0.03
    max_seq_length: int = 4096
    packing: bool = False

    # 数据
    train_data_path: str = "./data/lemon_train.jsonl"
    eval_data_path: Optional[str] = None

    # 保存
    save_steps: int = 500
    logging_steps: int = 50

    # 系统
    seed: int = 42
    resume_from_checkpoint: Optional[str] = None


# ============================================================
# 数据格式转换
# ============================================================

def convert_interaction_to_chatml(
    interactions: List[Dict],
    system_prompt: str = "你是 Lemon Code AI 助手，专注于代码生成、审查和工具调用。"
) -> List[Dict]:
    """将 InteractionLogger 数据转换为 ChatML 格式
    
    Args:
        interactions: [{"user": "...", "assistant": "..."}, ...]
        system_prompt: 系统提示词
    
    Returns:
        ChatML 格式: [{"messages": [{"role": "system", ...}, {"role": "user", ...}, ...]}]
    """
    chatml_data = []
    for interaction in interactions:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": interaction["user"]},
            {"role": "assistant", "content": interaction["assistant"]},
        ]
        chatml_data.append({"messages": messages})
    return chatml_data


def create_training_dataset(
    source_file: str,
    output_file: str,
    quality_threshold: float = 7.0,
    max_samples: int = 1000,
) -> int:
    """从 InteractionLogger 数据创建训练数据集
    
    Args:
        source_file: InteractionLogger 输出的 JSON 文件
        output_file: 输出的 ChatML JSONL 文件
        quality_threshold: 质量阈值（评分 >= 此值才纳入训练）
        max_samples: 最大样本数
    
    Returns:
        有效样本数
    """
    import json

    if not os.path.exists(source_file):
        print(f"[LemonTrainer] 数据源不存在: {source_file}")
        return 0

    with open(source_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    interactions = data.get("interactions", [])
    valid = []
    for item in interactions:
        score = item.get("quality_score", 0)
        if score >= quality_threshold and item.get("user") and item.get("assistant"):
            valid.append(item)

    if len(valid) > max_samples:
        valid = valid[:max_samples]

    chatml_data = convert_interaction_to_chatml(valid)

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        for item in chatml_data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"[LemonTrainer] 训练数据集创建完成: {len(valid)} 条 → {output_file}")
    return len(valid)


# ============================================================
# 训练主函数（伪代码 — 实际训练需要 GPU 环境）
# ============================================================

def train_qlora(config: LemonTrainConfig):
    """QLoRA 微调主函数
    
    注意: 此函数是伪代码框架，实际训练需要 GPU 环境和 Unsloth 库。
    在 GPU 环境中取消注释即可运行。
    """
    print("=" * 60)
    print("  Lemon AI Engine — QLoRA 训练")
    print(f"  基座模型: {config.base_model}")
    print(f"  输出目录: {config.output_dir}")
    print(f"  LoRA rank: {config.lora_r}")
    print(f"  学习率: {config.learning_rate}")
    print(f"  Epochs: {config.num_epochs}")
    print("=" * 60)

    # === 实际训练代码（需要 GPU 环境） ===
    # 取消注释以下代码即可在 GPU 环境中运行：
    """
    import torch
    from unsloth import FastLanguageModel
    from transformers import TrainingArguments
    from trl import SFTTrainer
    from datasets import load_dataset

    # 1. 加载模型
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=config.base_model,
        max_seq_length=config.max_seq_length,
        dtype=None,
        load_in_4bit=config.use_4bit,
    )

    # 2. 添加 LoRA adapter
    model = FastLanguageModel.get_peft_model(
        model,
        r=config.lora_r,
        target_modules=config.lora_target_modules,
        lora_alpha=config.lora_alpha,
        lora_dropout=config.lora_dropout,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=config.seed,
    )

    # 3. 加载数据
    dataset = load_dataset("json", data_files=config.train_data_path, split="train")

    # 4. 训练参数
    training_args = TrainingArguments(
        output_dir=config.output_dir,
        per_device_train_batch_size=config.per_device_train_batch_size,
        gradient_accumulation_steps=config.gradient_accumulation_steps,
        num_train_epochs=config.num_epochs,
        learning_rate=config.learning_rate,
        warmup_ratio=config.warmup_ratio,
        logging_steps=config.logging_steps,
        save_steps=config.save_steps,
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(),
        optim="adamw_8bit",
        seed=config.seed,
        report_to="none",
    )

    # 5. SFT Trainer
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        args=training_args,
        train_dataset=dataset,
        max_seq_length=config.max_seq_length,
        dataset_text_field="messages",
        packing=config.packing,
    )

    # 6. 开始训练
    trainer.train(resume_from_checkpoint=config.resume_from_checkpoint)

    # 7. 保存模型
    model.save_pretrained(config.output_dir)
    tokenizer.save_pretrained(config.output_dir)
    print(f"[LemonTrainer] 训练完成！模型已保存到 {config.output_dir}")
    """

    print("\n[LemonTrainer] 训练框架已就绪，等待 GPU 环境。")
    print("[LemonTrainer] 安装依赖: pip install unsloth trl datasets accelerate bitsandbytes peft")
    print("[LemonTrainer] 运行训练: python lemon_trainer.py --train")


# ============================================================
# GGUF 量化导出
# ============================================================

def export_to_gguf(
    model_dir: str,
    output_dir: str,
    quantization: str = "Q4_K_M",
):
    """将 LoRA 模型导出为 GGUF 格式
    
    Args:
        model_dir: 训练好的模型目录
        output_dir: GGUF 输出目录
        quantization: 量化级别 (Q4_K_M / Q5_K_M / Q8_0)
    """
    print("=" * 60)
    print("  Lemon AI Engine — GGUF 量化导出")
    print(f"  模型目录: {model_dir}")
    print(f"  量化级别: {quantization}")
    print("=" * 60)

    # === 实际导出代码（需要 llama.cpp） ===
    """
    # Step 1: 合并 LoRA adapter
    # python -m llama_cpp.convert_lora_to_gguf \\
    #   --base_model {base_model} \\
    #   --lora_path {model_dir} \\
    #   --output {output_dir}/lemon-merged.gguf

    # Step 2: 量化
    # ./llama-quantize {output_dir}/lemon-merged.gguf \\
    #   {output_dir}/lemon-{quantization}.gguf \\
    #   {quantization}
    """

    print(f"\n[LemonTrainer] GGUF 导出框架已就绪。")
    print(f"[LemonTrainer] 安装 llama.cpp 后运行:")
    print(f"  python convert_hf_to_gguf.py {model_dir} --outtype f16")
    print(f"  ./llama-quantize {model_dir}/ggml-model-f16.gguf {quantization}")


# ============================================================
# Ollama Modelfile 生成
# ============================================================

def create_ollama_modelfile(
    gguf_path: str,
    model_name: str = "lemon-code",
    output_path: str = "./Modelfile",
):
    """创建 Ollama Modelfile"""
    template = f"""# Lemon Code AI Model
FROM {gguf_path}

TEMPLATE \"\"\"<|im_start|>system
{{{{ .System }}}}<|im_end|>
<|im_start|>user
{{{{ .Prompt }}}}<|im_end|>
<|im_start|>assistant
\"\"\"

PARAMETER temperature 0.3
PARAMETER top_p 0.9
PARAMETER top_k 40
PARAMETER num_predict 4096
PARAMETER repeat_penalty 1.1
PARAMETER stop "<|im_start|>"
PARAMETER stop "<|im_end|>"

SYSTEM \"\"\"你是 Lemon Code AI 助手。
专注于代码生成、审查、Agent 工具调用。
回答要简洁专业，给出可执行的代码示例。
工具调用格式：<tool_call>{{"name": "xxx", "arguments": {{...}}}}</tool_call>\"\"\"
"""

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(template)

    print(f"[LemonTrainer] Modelfile 已创建: {output_path}")
    print(f"[LemonTrainer] 部署命令:")
    print(f"  ollama create {model_name} -f {output_path}")
    print(f"  ollama run {model_name}")

    return output_path


# ============================================================
# 数据增强
# ============================================================

def augment_code_data(
    samples: List[Dict],
    augmentation_factor: int = 2,
) -> List[Dict]:
    """代码数据增强
    
    通过以下方式扩充训练数据:
    1. 变量名随机替换（保持语义）
    2. 注释风格变换（中文/英文/无注释）
    3. 代码格式变换（缩进风格、空行）
    4. 同一问题的不同表述
    
    Args:
        samples: 原始 ChatML 格式样本
        augmentation_factor: 增强倍数
    
    Returns:
        增强后的样本列表
    """
    import random
    
    augmented = list(samples)
    
    # 同义表述模板
    prompt_variations = [
        lambda p: p.replace("写一个", "请编写一个"),
        lambda p: p.replace("写一个", "帮我实现一个"),
        lambda p: p.replace("写一个", "创建一个"),
        lambda p: p.replace("写一个", "生成一个"),
        lambda p: p.replace("请", "麻烦"),
        lambda p: p.replace("帮我", "请帮我"),
    ]
    
    # 代码风格变换
    code_variations = [
        lambda c: c.replace("    ", "  "),  # 4空格→2空格
        lambda c: "\n".join(line for line in c.split("\n") if line.strip()),  # 去空行
        lambda c: c.replace(" = ", "="),  # 紧凑风格
    ]
    
    for _ in range(augmentation_factor - 1):
        for sample in samples:
            new_sample = {
                "messages": [
                    dict(msg) for msg in sample["messages"]
                ]
            }
            
            # 变换用户消息
            for msg in new_sample["messages"]:
                if msg["role"] == "user":
                    variation = random.choice(prompt_variations)
                    msg["content"] = variation(msg["content"])
                elif msg["role"] == "assistant":
                    # 随机变换代码风格
                    if random.random() < 0.3:
                        variation = random.choice(code_variations)
                        msg["content"] = variation(msg["content"])
            
            augmented.append(new_sample)
    
    return augmented


def create_balanced_dataset(
    source_file: str,
    output_file: str,
    quality_threshold: float = 7.0,
    max_samples: int = 1000,
    task_balance: bool = True,
) -> Dict:
    """创建平衡训练数据集
    
    按任务类型均衡采样，确保模型不会偏向某一类任务。
    
    Task types:
    - code_generation: 代码生成
    - code_review: 代码审查
    - debugging: 调试
    - refactoring: 重构
    - testing: 测试
    - documentation: 文档
    - general: 通用
    """
    import json
    
    if not os.path.exists(source_file):
        print(f"[LemonTrainer] 数据源不存在: {source_file}")
        return {"success": False, "error": "数据源不存在", "samples": 0}
    
    with open(source_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    interactions = data.get("interactions", [])
    
    # 按任务类型分组
    by_task = {}
    for item in interactions:
        score = item.get("quality_score", 0)
        if score >= quality_threshold and item.get("user") and item.get("assistant"):
            task_type = item.get("task_type", "general")
            by_task.setdefault(task_type, []).append(item)
    
    # 均衡采样
    if task_balance:
        per_task = max_samples // max(len(by_task), 1)
        balanced = []
        for task_type, items in by_task.items():
            sampled = items[:per_task]
            balanced.extend(sampled)
        
        if len(balanced) > max_samples:
            balanced = balanced[:max_samples]
    else:
        balanced = list(interactions)[:max_samples]
    
    # 转换为 ChatML
    chatml_data = convert_interaction_to_chatml(balanced)
    
    # 数据增强
    if len(chatml_data) < 500:
        print(f"[LemonTrainer] 数据不足 ({len(chatml_data)} 条)，启用增强...")
        chatml_data = augment_code_data(chatml_data, augmentation_factor=2)
    
    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        for item in chatml_data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    
    result = {
        "success": True,
        "samples": len(chatml_data),
        "original": len(balanced),
        "augmented": len(chatml_data) - len(balanced),
        "task_distribution": {t: len(items) for t, items in by_task.items()},
    }
    print(f"[LemonTrainer] 平衡数据集创建完成: {result}")
    return result


# ============================================================
# 一键部署脚本生成
# ============================================================

def generate_deploy_script(output_dir: str) -> str:
    """生成一键部署脚本
    
    创建 deploy.sh / deploy.ps1 脚本，自动化从模型到 Ollama 的部署流程。
    """
    script_path = os.path.join(output_dir, "deploy_lemon.ps1")
    
    script_content = '''# Lemon AI Engine 一键部署脚本 (Windows PowerShell)
# 自动完成: 合并 LoRA → GGUF 量化 → Ollama 注册

param(
    [string]$ModelDir = "./lemon-model-output",
    [string]$QuantMethod = "Q4_K_M",
    [string]$ModelName = "lemon-code",
    [string]$LlamaCppDir = "./llama.cpp"
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Lemon AI Engine — 一键部署" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Step 1: 合并 LoRA adapter
Write-Host "[1/4] 合并 LoRA adapter..." -ForegroundColor Yellow
$mergeScript = Join-Path $LlamaCppDir "convert_lora_to_gguf.py"
if (Test-Path $mergeScript) {
    python $mergeScript --base Qwen/Qwen2.5-Coder-7B-Instruct --lora $ModelDir --out "$ModelDir/lemon-merged.gguf"
} else {
    Write-Host "  跳过 (llama.cpp 未安装)" -ForegroundColor Gray
}

# Step 2: GGUF 量化
Write-Host "[2/4] GGUF 量化 ($QuantMethod)..." -ForegroundColor Yellow
$quantizeBin = Join-Path $LlamaCppDir "build/bin/quantize.exe"
if (Test-Path $quantizeBin) {
    & $quantizeBin "$ModelDir/lemon-merged.gguf" "$ModelDir/lemon-$QuantMethod.gguf" $QuantMethod
} else {
    Write-Host "  跳过 (llama.cpp 未编译)" -ForegroundColor Gray
}

# Step 3: 创建 Modelfile
Write-Host "[3/4] 创建 Ollama Modelfile..." -ForegroundColor Yellow
$modelfileContent = @"
FROM $ModelDir/lemon-$QuantMethod.gguf

TEMPLATE """<|im_start|>system
{{ .System }}<|im_end|>
<|im_start|>user
{{ .Prompt }}<|im_end|>
<|im_start|>assistant
"""

PARAMETER temperature 0.3
PARAMETER top_p 0.9
PARAMETER num_predict 4096
PARAMETER stop "<|im_start|>"
PARAMETER stop "<|im_end|>"

SYSTEM """你是 Lemon Code AI 助手，基于 Qwen2.5-Coder 微调。专注于代码生成、审查、Agent 工具调用。"""
"@
$modelfileContent | Out-File -FilePath "$ModelDir/Modelfile" -Encoding UTF8

# Step 4: 注册到 Ollama
Write-Host "[4/4] 注册到 Ollama..." -ForegroundColor Yellow
$ggufPath = Join-Path $ModelDir "lemon-$QuantMethod.gguf"
if (Test-Path $ggufPath) {
    ollama create $ModelName -f "$ModelDir/Modelfile"
    Write-Host "  部署完成! 运行: ollama run $ModelName" -ForegroundColor Green
} else {
    Write-Host "  GGUF 文件不存在，请先完成量化步骤" -ForegroundColor Red
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  部署流程完成" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
'''
    
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script_content)
    
    print(f"[LemonTrainer] 部署脚本已创建: {script_path}")
    return script_path


# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Lemon AI Engine 训练工具")
    parser.add_argument("--mode", choices=["qlora", "lora", "full", "export", "modelfile"],
                        default="qlora", help="运行模式")
    parser.add_argument("--base_model", default="Qwen/Qwen2.5-Coder-7B-Instruct",
                        help="基座模型")
    parser.add_argument("--train_data", default="./data/lemon_train.jsonl",
                        help="训练数据路径")
    parser.add_argument("--output_dir", default="./lemon-model-output",
                        help="输出目录")
    parser.add_argument("--lora_r", type=int, default=16, help="LoRA rank")
    parser.add_argument("--epochs", type=int, default=3, help="训练轮数")
    parser.add_argument("--lr", type=float, default=2e-4, help="学习率")
    parser.add_argument("--quantization", default="Q4_K_M", help="GGUF 量化级别")
    parser.add_argument("--train", action="store_true", help="实际执行训练")

    args = parser.parse_args()

    config = LemonTrainConfig(
        mode=args.mode,
        base_model=args.base_model,
        output_dir=args.output_dir,
        train_data_path=args.train_data,
        lora_r=args.lora_r,
        num_epochs=args.epochs,
        learning_rate=args.lr,
    )

    if args.mode == "modelfile":
        create_ollama_modelfile(
            f"./lemon-model-output/lemon-{args.quantization}.gguf",
            output_path=os.path.join(args.output_dir, "Modelfile"),
        )
    elif args.mode == "export":
        export_to_gguf(args.output_dir, args.output_dir, args.quantization)
    elif args.train:
        train_qlora(config)
    else:
        print(f"[LemonTrainer] 模式: {args.mode}（使用 --train 执行实际训练）")
        train_qlora(config)


if __name__ == "__main__":
    main()