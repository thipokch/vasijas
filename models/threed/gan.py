import os
import time
import torch
from torch import optim
from torch import nn
from utils import utils3D, utils
from torch.utils import data
from torch.autograd import Variable
from models.threed.generator import _G
from models.threed.discriminator import _D
import pickle
import numpy as np
from torchsummary import summary


class GAN(object):
    """
    See https://github.com/meetshah1995/tf-3dgan and https://github.com/rimchang/3DGAN-Pytorch 
    for more info on 3DGANs
    """
    def __init__(self, epochs=100, sample=25, batch=32, betas=(0.5, 0.5),
                 g_lr=0.0025, d_lr= 0.001, cube_len=64, latent_v=200,
                 data_path='output/output_obj/', transforms=None):
        # parameters
        self.epoch = epochs
        self.betas = betas
        self.sample_num = sample
        self.batch_size = batch
        self.save_dir = '/tmp/'
        self.result_dir = '/tmp/'
        self.log_dir = '/tmp/'
        self.gpu_mode = True
        self.dataset = 'vasijas'
        self.model_name = 'GAN3D'
        self.z_dim = latent_v
        
        # networks init
        self.G = _G(z_latent_space=latent_v)
        self.D = _D(cube_len=cube_len)
        self.G_optimizer = optim.Adam(self.G.parameters(),
                                      lr=g_lr, betas=self.betas)
        self.D_optimizer = optim.Adam(self.D.parameters(),
                                      lr=d_lr, betas=self.betas)

        if self.gpu_mode:
            self.G.cuda()
            self.D.cuda()
            # self.BCE_loss = nn.BCELoss().cuda()

        self.BCE_loss = nn.BCELoss()

        print('---------- Networks architecture Generator -------------')
        summary(self.G,  (1, latent_v))
        print('---------- Networks architecture Discriminator  --------')
        summary(self.D, (1, cube_len, cube_len, cube_len))

        # load dataset
        imagenet_data = utils3D.VesselsDataset(data_path)

        self.data_loader =  data.DataLoader(imagenet_data, 
                                            batch_size=self.batch_size,
                                            shuffle=True, num_workers=1)
           
    def save(self):
        save_dir = os.path.join(self.save_dir, self.dataset, self.model_name)

        if not os.path.exists(save_dir):
            os.makedirs(save_dir)

        torch.save(self.G.state_dict(), os.path.join(save_dir, self.model_name + '_G.pkl'))
        torch.save(self.D.state_dict(), os.path.join(save_dir, self.model_name + '_D.pkl'))

        with open(os.path.join(save_dir, self.model_name + '_history.pkl'), 'wb') as f:
            pickle.dump(self.train_hist, f)

    def load(self):
        save_dir = os.path.join(self.save_dir, self.dataset, self.model_name)

        self.G.load_state_dict(torch.load(os.path.join(save_dir, self.model_name + '_G.pkl')))
        self.D.load_state_dict(torch.load(os.path.join(save_dir, self.model_name + '_D.pkl')))

    def visualize_results(self, samples, epoch):
        output_path = '/'.join([self.result_dir, self.dataset,
                               self.model_name])
        if not os.path.exists(output_path):
            os.makedirs(output_path)
        utils3D.save_plot_voxels(samples, output_path, epoch)

    def train(self):
        self.train_hist = {}
        self.train_hist['D_loss'] = []
        self.train_hist['G_loss'] = []
        self.train_hist['per_epoch_time'] = []
        self.train_hist['total_time'] = []

        print('training start!!')
        start_time = time.time()
        for epoch in range(self.epoch):
            print('epoch nro {}'.format(epoch))
            epoch_start_time = time.time()
            
            for i,  X in enumerate(self.data_loader):
                print("Batch nro {}".format(i))    
                X = utils3D.var_or_cuda(X)      
                
                if X.size()[0] != int(self.batch_size):
                    print("batch_size != {} drop last incompatible batch".format(int(self.batch_size)))
                    continue

                Z = utils3D.var_or_cuda(torch.Tensor(self.batch_size, self.z_dim).normal_(0, 0.33))
                self.y_real_, self.y_fake_ = utils3D.var_or_cuda(torch.ones(self.batch_size)), \
                                             utils3D.var_or_cuda(torch.zeros(self.batch_size))

                # update D network
                D_real = self.D(X)
                D_real_loss = self.BCE_loss(D_real, self.y_real_)

                fake = self.G(Z)
                D_fake = self.D(fake)
                D_fake_loss = self.BCE_loss(D_fake, self.y_fake_)

                D_loss = D_real_loss + D_fake_loss
                self.train_hist['D_loss'].append(D_loss.item())


                d_real_acu = torch.ge(D_real.squeeze(), 0.5).float()
                d_fake_acu = torch.le(D_fake.squeeze(), 0.5).float()
                d_total_acu = torch.mean(torch.cat((d_real_acu, d_fake_acu), 0))

                if d_total_acu <= 0.8:
                    self.D.zero_grad()
                    D_loss.backward()
                    self.D_optimizer.step()

                # update G network
                Z = utils3D.var_or_cuda(torch.Tensor(self.batch_size, self.z_dim).normal_(0, 0.33))
                fake = self.G(Z)
                D_fake = self.D(fake)
                G_loss = self.BCE_loss(D_fake, self.y_real_)
                self.train_hist['G_loss'].append(G_loss.item())

                self.D.zero_grad()
                self.G.zero_grad()
                G_loss.backward()
                self.G_optimizer.step()

            print("Epoch: [%2d] [%4d/%4d] D_loss: %.8f, G_loss: %.8f" %
                 ((epoch + 1), (epoch + 1), self.data_loader.dataset.__len__() // 
                 self.batch_size, D_loss.item(), G_loss.item()))
            samples = fake.cpu().data[:self.sample_num].squeeze().numpy()
            self.visualize_results(samples, (epoch+1))

            self.train_hist['per_epoch_time'].append(time.time() - epoch_start_time)
            self.save()

        self.train_hist['total_time'].append(time.time() - start_time)
        print("Avg one epoch time: %.2f, total %d epochs time: %.2f" % (np.mean(self.train_hist['per_epoch_time']),
              self.epoch, self.train_hist['total_time'][0]))
        print("Training finish!... save training results")

        #animation_path = '/'.join([self.result_dir, self.dataset,
        #                          self.model_name, self.model_name])
        #if not os.path.exists(animation_path):
        #    os.makedirs(animation_path)
        #utils.generate_animation(animation_path, self.epoch)
        #utils.loss_plot(self.train_hist, os.path.join(self.save_dir, self.dataset, self.model_name), self.model_name)
