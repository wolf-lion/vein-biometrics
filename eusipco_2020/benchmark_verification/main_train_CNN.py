"""
This code is generated by Ridvan Salih KUZU @UNIROMA3
LAST EDITED:  02.03.2020
ABOUT SCRIPT:
It is a main script for training a verification system for a given database.
It considers CUSTOM PENALTY functions.
The related databases should be placed in data_bosphorus, data_polyup, and data_sdumla folders

"""
import numpy as np
import argparse
import torch
from torch.optim import lr_scheduler
from utils import FullPairComparer,AverageMeter, evaluate, plot_roc, plot_DET_with_EER, plot_density,accuracy
from models import DenseNet161_Modified as net
from benchmark_verification import get_dataloader
from losses import *
import shutil
from torch.nn import CrossEntropyLoss
import pandas as pd
import os
from itertools import chain
import csv

parser = argparse.ArgumentParser(description='Vein Verification')

parser.add_argument('--start-epoch', default=0, type=int, metavar='SE',
                    help='start epoch (default: 0)')
parser.add_argument('--num-epochs', default=120, type=int, metavar='NE',
                    help='number of epochs to train (default: 90)')
parser.add_argument('--num-classes', default=250, type=int, metavar='NC',
                    help='number of clases (default: 318)')
parser.add_argument('--embedding-size', default=1024, type=int, metavar='ES',
                    help='embedding size (default: 128)')
parser.add_argument('--batch-size', default=32, type=int, metavar='BS',
                    help='batch size (default: 128)')
parser.add_argument('--num-workers', default=16, type=int, metavar='NW',
                    help='number of workers (default: 8)')
parser.add_argument('--learning-rate', default=0.01, type=float, metavar='LR',
                    help='learning rate (default: 0.01)') #seems best when SWG off
parser.add_argument('--weight-decay', default=0.01, type=float, metavar='WD',
                    help='weight decay (default: 0.01)') #seems best when SWG off
parser.add_argument('--scale-rate', default=32, type=float, metavar='SC',
                    help='scale rate (default: 0.001)')
parser.add_argument('--margin', default=0.5, type=float, metavar='MG',
                    help='margin (default: 0.5)')
parser.add_argument('--database-dir', default='data_polyup/Database', type=str,
                    help='path to the database root directory')
parser.add_argument('--train-dir', default='data_polyup/CSVFiles/train_dis.csv', type=str,
                    help='path to train root dir')
parser.add_argument('--valid-dir', default='data_polyup/CSVFiles/val_dis.csv', type=str,
                    help='path to valid root dir')
parser.add_argument('--test-dir', default='data_polyup/CSVFiles/test_pairs_dis.csv', type=str,
                    help='path to test root dir')
parser.add_argument('-e', '--evaluate', dest='evaluate', action='store_true',
                    help='evaluate model on test set')
parser.add_argument('--type', default='aamp', type=str, metavar='MG',
                    help='type (default: aamp)')
parser.add_argument('--outdir', default='modeldir/00/03/', type=str,
                    help='Out Directory (default: model)')
parser.add_argument('--logdir', default='data_polyup/CSVFiles/cnn_logs.csv', type=str,
                    help='path to log dir')

args = parser.parse_args()
#device  = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
global best_losss
best_losss = 100
global best_test
best_test=100



def main():
    if not os.path.exists(args.outdir):
        os.makedirs(args.outdir)

    #device = torch.device("cuda:0")

    criterion = CrossEntropyLoss().cuda()
    if args.type == 'norm':
        loss_metric = NormSoftmax(args.embedding_size, args.num_classes, args.scale_rate).cuda()
    elif args.type == 'aamp':
        loss_metric = ArcMarginProduct(args.embedding_size, args.num_classes, s=args.scale_rate, m=args.margin).cuda()
    elif args.type == 'lmcp':
        loss_metric = AddMarginProduct(args.embedding_size, args.num_classes, s=args.scale_rate, m=args.margin).cuda()
    elif args.type == 'sphere':
        loss_metric = SphereProduct(args.embedding_size, args.num_classes, m=int(args.margin)).cuda()
    elif args.type == 'lgm':
        loss_metric = CovFixLGM(args.embedding_size, args.num_classes, args.margin).cuda()
    elif args.type == 'lgm2':
        loss_metric = LGMLoss(args.embedding_size, args.num_classes, args.margin).cuda()
    elif args.type == 'none':
        loss_metric = None

    if loss_metric is not None:
        model = net(embedding_size=args.embedding_size, class_size=args.num_classes, only_embeddings=True,pretrained=True)
        to_be_optimized=chain(model.parameters(), loss_metric.parameters())
    else:
        model = net(embedding_size=args.embedding_size, class_size=args.num_classes, only_embeddings=False,pretrained=True)
        to_be_optimized = model.parameters()

    model = torch.nn.DataParallel(model).cuda()
    optimizer = torch.optim.SGD(to_be_optimized,
                                lr=args.learning_rate,
                                momentum=0.9,
                                weight_decay=args.weight_decay)


    #scheduler = lr_scheduler.StepLR(optimizer, step_size=30, gamma=0.1)
    scheduler = lr_scheduler.ReduceLROnPlateau(optimizer, cooldown=2,verbose=True)

    if args.start_epoch != 0:
        checkpoint = torch.load(args.outdir+'/model_checkpoint.pth.tar')
        args.start_epoch = checkpoint['epoch']
        model.load_state_dict(checkpoint['state_dict'])
        optimizer.load_state_dict(checkpoint['optimizer'])
    if args.evaluate:
        checkpoint = torch.load(args.outdir+'/model_best.pth.tar')
        args.start_epoch = checkpoint['epoch']
        model.load_state_dict(checkpoint['state_dict'])
        optimizer.load_state_dict(checkpoint['optimizer'])
        data_loaders = get_dataloader(args.database_dir,args.train_dir, args.valid_dir, args.test_dir,
                                      args.batch_size, args.num_workers)
        test(model,data_loaders['test'],'00',is_graph=True)

    else:
        for epoch in range(args.start_epoch, args.num_epochs + args.start_epoch):
            print(80 * '=')
            print('Epoch [{}/{}]'.format(epoch, args.num_epochs + args.start_epoch - 1))

            data_loaders = get_dataloader(args.database_dir,args.train_dir, args.valid_dir,args.test_dir,
                                      args.batch_size, args.num_workers)

            train(model, optimizer, epoch, data_loaders['train'],criterion,loss_metric)
            is_best, acc, loss=validate(model, optimizer, epoch, data_loaders['valid'], criterion,loss_metric)
            scheduler.step(loss)
            if is_best and acc>100:
                test(model,data_loaders['test'],epoch,is_graph=True)

        print(80 * '=')

        ## MODEL EVALUATION LOGGING ##
        data_loaders = get_dataloader(args.database_dir, args.train_dir, args.valid_dir, args.test_dir,
                                  args.batch_size, args.num_workers)
        checkpoint = torch.load(args.outdir + '/model_best.pth.tar')
        model.load_state_dict(checkpoint['state_dict'])
        EER = test(model, data_loaders['test'], epoch,is_graph=False)

        header = ['weight_decay', 'learning_rate', 'scale', 'margin','type', 'batch_size', 'embedding_size', 'EER', 'out_dir' ]
        info = [args.weight_decay, args.learning_rate, args.scale_rate, args.margin, args.type, args.batch_size,args.embedding_size, EER, args.outdir]

        if not os.path.exists(args.logdir):
            with open(args.logdir, 'w') as file:
                logger = csv.writer(file)
                logger.writerow(header)
                logger.writerow(info)
        else:
            with open(args.logdir, 'a') as file:
                logger = csv.writer(file)
                logger.writerow(info)


def test(model, dataloader,epoch,is_graph=False):
    global best_test
    labels, distances = [], []
    with torch.set_grad_enabled(False):
        comparer = FullPairComparer().cuda()
        model.eval()
        for batch_idx, (data1, data2, target) in enumerate(dataloader):
            dist = []
            target = target.cuda(non_blocking=True)

            output1 = model(data1,False)
            output2 = model(data2,False)
            dist = comparer(output1, output2) #TODO: sign - torch.sign()
            #dist = comparer(torch.sign(F.relu(output1)), torch.sign(F.relu(output2)))  # TODO: sign - torch.sign()
            distances.append(dist.data.cpu().numpy())
            labels.append(target.data.cpu().numpy())
            if batch_idx % 50 == 0:
                print('Batch-Index -{}'.format(str(batch_idx)))


    labels = np.array([sublabel for label in labels for sublabel in label])
    distances = np.array([subdist for dist in distances for subdist in dist])
    tpr, fpr, fnr, fpr_optimum, fnr_optimum, accuracy, threshold = evaluate(distances, labels)

    EER = np.mean(fpr_optimum + fnr_optimum) / 2
    print('TEST - Accuracy           = {:.12f}'.format(accuracy))
    print('TEST - EER                = {:.12f}'.format(EER))
    is_best = EER <= best_test
    best_test = min(EER, best_test)

    if is_best and is_graph:
        plot_roc(fpr, tpr, figure_name=args.outdir + '/Test_ROC-{}.png'.format(epoch))
        plot_DET_with_EER(fpr, fnr, fpr_optimum, fnr_optimum,
                          figure_name=args.outdir + '/Test_DET-{}.png'.format(epoch))
        plot_density(distances, labels, figure_name=args.outdir + '/Test_DENSITY-{}.png'.format(epoch))
        df_results = pd.DataFrame({'distances': distances.transpose(), 'labels': labels.transpose()})
        df_results.to_csv(args.outdir + "/test_outputs.csv", index=False)

        if args.evaluate is False:
            shutil.copyfile(args.outdir + '/model_best.pth.tar', args.outdir + '/test_model_best.pth.tar')

    return EER


def train(model, optimizer, epoch, dataloader, criterion, metric):
    with torch.set_grad_enabled(True):
        losses = AverageMeter()
        top1 = AverageMeter()
        model.train()

        for batch_idx, (data, target,_) in enumerate(dataloader):
            optimizer.zero_grad()
            target = target.cuda(non_blocking=True)
            outputs = model(data.cuda())
            if metric is not None:
                outputs = metric(outputs, target)
            loss = criterion(outputs,target)

            prec1, prec5 = accuracy(outputs, target, topk=(1, 5))
            losses.update(loss.item(), data.size(0))
            top1.update(prec1[0], data.size(0))
            loss.backward()
            optimizer.step()
            if batch_idx % 25 == 0:
                print('Step-{} Prec@1 {top1.avg:.5f} loss@1 - {loss.avg:.5f}'.format(batch_idx, top1=top1, loss=losses))

        print('*TRAIN Prec@1 {top1.avg:.5f} - loss@1 {loss.avg:.5f}'.format(top1=top1, loss=losses))

def validate(model, optimizer, epoch, dataloader, criterion, metric):
    global best_losss
    with torch.set_grad_enabled(False):
        losses = AverageMeter()
        top1 = AverageMeter()

        model.eval()

        for batch_idx, (data, target,_) in enumerate(dataloader):
            target = target.cuda(non_blocking=True)
            outputs = model(data.cuda())
            if metric is not None:
                outputs = metric(outputs, target)
            loss = criterion(outputs, target)
            prec1, prec5 = accuracy(outputs, target, topk=(1, 5))
            losses.update(loss.item(), data.size(0))
            top1.update(prec1[0], data.size(0))
            if batch_idx % 5 == 0:
                print('Step-{} Prec@1 {top1.avg:.5f} loss@1 - {loss.avg:.5f}'.format(batch_idx,top1=top1,loss=losses))

        print('*VALID Prec@1 {top1.avg:.5f} - loss@1 {loss.avg:.5f}'.format(top1=top1,loss=losses))
        is_best = losses.avg <= best_losss
        best_losss = min(losses.avg, best_losss)
        torch.save({'epoch': epoch+1,
                    'state_dict': model.state_dict(),
                    'optimizer': optimizer.state_dict()},
                   args.outdir+'/model_checkpoint.pth.tar')
        if is_best:
            shutil.copyfile(args.outdir+'/model_checkpoint.pth.tar', args.outdir+'/model_best.pth.tar')

        return is_best, top1.avg, losses.avg


if __name__ == '__main__':
    main()


