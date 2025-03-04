#!/usr/bin/env python
# encoding: utf-8
'''
@license: (C) Copyright 2021, Hey.
@author: Hey
@email: sanyuan.hy@alibaba-inc.com
@tel: 137****6540
@datetime: 2023/5/5 09:55
@project: LucaOne
@file: evaluator
@desc: evaluator for LucaOne
'''
import sys, torch
sys.path.append(".")
sys.path.append("..")
sys.path.append("../src")
try:
    from utils import to_device, concat_output, calc_avg_loss, calc_eval_test_loss, print_batch
    from multi_files_stream_dataloader import *
    from common.multi_label_metrics import metrics_multi_label
    from common.metrics import metrics_multi_class, metrics_binary
except ImportError:
    from src.utils import to_device, concat_output, calc_avg_loss, calc_eval_test_loss, print_batch
    from src.multi_files_stream_dataloader import *
    from src.common.multi_label_metrics import metrics_multi_label
    from src.common.metrics import metrics_multi_class, metrics_binary


def evaluate(args, model, parse_row_func, batch_data_func, prefix="", log_fp=None):
    '''
    evaluation
    :param args:
    :param model:
    :param parse_row_func:
    :param batch_data_func:
    :param prefix:
    :param log_fp:
    :return:
    '''
    save_output_dir = os.path.join(args.output_dir, prefix)
    print("\nEvaluating information dir: ", save_output_dir)
    if args.local_rank in [-1, 0] and not os.path.exists(save_output_dir):
        os.makedirs(save_output_dir)
    dev_dataloader = MultiFilesStreamLoader(args.dev_data_dir,
                                            args.per_gpu_eval_batch_size,
                                            args.buffer_size,
                                            parse_row_func=parse_row_func,
                                            batch_data_func=batch_data_func,
                                            pretrain_task_level_type=args.pretrain_task_level_type,
                                            gene_label_size_dict=args.gene_label_size_dict,
                                            gene_output_mode_dict=args.gene_output_mode_dict,
                                            prot_label_size_dict=args.prot_label_size_dict,
                                            prot_output_mode_dict=args.prot_output_mode_dict,
                                            pair_label_size_dict=args.pair_label_size_dict,
                                            pair_output_mode_dict=args.pair_output_mode_dict,
                                            header=True,
                                            shuffle=False)

    # evaluate
    if log_fp:
        log_fp.write("***** Running evaluation {} *****\n".format(prefix))
        log_fp.write("Dev Dataset Instantaneous batch size per GPU = %d\n" % args.per_gpu_eval_batch_size)
        log_fp.write("#" * 50 + "\n")
        log_fp.flush()

    nb_steps = 0

    # total losses
    total_losses = {}

    # predicted prob
    pred_scores = None

    # ground truth
    out_label_ids = None
    #
    total_loss = 0
    done_sample_num = 0
    model.eval()
    for step, batch in enumerate(dev_dataloader):
        # evaluate
        with torch.no_grad():
            batch, cur_sample_num = to_device(args.device, batch)
            done_sample_num += cur_sample_num
            try:
                output = model(**batch,
                               output_keys=args.gene_output_keys,
                               output_keys_b=args.prot_output_keys,
                               pair_output_keys=args.pair_output_keys,
                               output_attentions=True,
                               output_hidden_states=True)
            except Exception as e:
                with open("evaluate_exception_info_%d" % args.local_rank, "a+") as afp:
                    afp.write(str(e) + "\n")
                    afp.flush()
                with open("evaluate_exception_input_%d" % args.local_rank, "a+") as afp:
                    afp.write(str(batch) + "\n")
                    afp.flush()
                debug_path = "./debug/dev/local_rank%s/%d/" % ("_" + str(args.local_rank) if args.local_rank >= 0 else "", step)
                if not os.path.exists(debug_path):
                    os.makedirs(debug_path)
                with open(os.path.join(debug_path, "evaluate_exception_input_details.txt"), "a+") as afp:
                    print_batch(batch, key=None, debug_path=debug_path, wfp=afp, local_rank=args.local_rank)
                    afp.flush()
                continue
            if isinstance(output, dict):
                losses = []
                outputs = []
                if output.losses:
                    losses.append(output.losses)
                if output.losses_b:
                    losses.append(output.losses_b)
                if output.pair_losses:
                    losses.append(output.pair_losses)
                if output.outputs:
                    outputs.append(output.outputs)
                if output.outputs_b:
                    outputs.append(output.outputs_b)
                if output.pair_outputs:
                    outputs.append(output.pair_outputs)
            else:
                losses, outputs = output[:2]
            current_losses, total_losses, total_loss, cur_loss = calc_eval_test_loss(losses, total_losses, total_loss)

            print("\rEval, Batch: %06d, Sample Num: %d, Cur Loss: %0.6f, Avg Loss: %0.6f" % (step + 1, done_sample_num,
                                                                                             cur_loss, total_loss/(nb_steps + 1)),
                  end="", flush=True)
            nb_steps += 1
            '''
            if pred_scores is not None:
                pred_scores = concat_output(batch["token"], outputs, out_label_ids, pred_scores)
            '''
    all_result, loss, loss_detail = calc_avg_loss(total_losses, nb_steps)
    with open(os.path.join(save_output_dir, "dev_metrics.txt"), "w") as writer:
        writer.write("***** Dev results {} *****\n".format(prefix))
        writer.write("Dev average loss = %0.6f" % loss)
        writer.write("Dev detail loss = %s" % str(loss_detail))
        for key in sorted(all_result.keys()):
            writer.write("%s = %s\n" % (key, str(all_result[key])))
    return all_result
