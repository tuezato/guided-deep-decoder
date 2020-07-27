import torch
import torch.nn as nn
from .common import *
#import torch.nn.functional as F

# attention module for FRU
class attention_FRU(nn.Module):
    def __init__(self, num_channels_down, act_fun='LeakyReLU'):
        super().__init__()
        # layers to generate conditional convolution weights
        self.gen_se_weights1 = nn.Sequential(
                    conv(num_channels_down, num_channels_down, 1, bias=True, pad='reflection'),
                    act(act_fun),
                    nn.Sigmoid())

        # create conv layers
        self.conv_1 = conv(num_channels_down, num_channels_down, 1, bias=True, pad='reflection')
        self.norm_1 = bn(num_channels_down)
        self.actvn = act(act_fun)
        
    def forward(self, guide, x):
        se_weights1 = self.gen_se_weights1(guide)
        dx = self.conv_1(x)
        dx = self.norm_1(dx)
        dx = torch.mul(dx, se_weights1)
        out = self.actvn(dx)

        return out

# attention module for URU
class attention_URU(nn.Module):
    def __init__(self, num_channels_down, act_fun='LeakyReLU', upsample_mode = 'bilinear', need_bias = True, pad = 'reflection'):
        super().__init__()
        
        # generate conditional convolution weights
        self.weight_map = nn.Sequential(
                        conv(num_channels_down, num_channels_down, 1, bias= need_bias, pad=pad),
                        act(act_fun),
                        nn.Sigmoid())
        
        # upsampling and channel-wise normalization
        self.upsample_norm = nn.Sequential(
                        nn.Upsample(scale_factor=2, mode=upsample_mode),
                        nn.BatchNorm2d(num_channels_down, affine=False))
        
    def forward(self, guide, x):
        x_upsample = self.upsample_norm(x)
        weight = self.weight_map(guide)
        out = torch.mul(x_upsample, weight)
        return out

# guided deep decoder
class gdd(nn.Module):
    def __init__(self, num_input_channels=3, num_output_channels=3, 
        num_channels_down=50, num_channels_up=50, num_channels_skip=4, 
        filter_size_down=3, filter_size_up=3, filter_skip_size=1,
        need_sigmoid=True, need_bias=True, 
        pad='reflection', upsample_mode='bilinear', downsample_mode='stride', act_fun='LeakyReLU', 
        need1x1_up=True):
        super().__init__()
        
        
        self.FRU = attention_FRU(num_channels_down)
        self.URU = attention_URU(num_channels_down, act_fun='LeakyReLU', upsample_mode = 'bilinear', need_bias = True, pad = 'reflection')
    
        self.guide_enc = nn.Sequential(
                    conv(3, num_channels_down, filter_size_down, bias=need_bias, pad=pad),
                    bn(num_channels_down),
                    act(act_fun))
        
        self.enc = nn.Sequential(
                    conv(num_channels_down, num_channels_down, filter_size_down, 2, bias=need_bias, pad=pad, downsample_mode=downsample_mode), 
                    bn(num_channels_down), 
                    act(act_fun),
                    
                    conv(num_channels_down, num_channels_down, filter_size_down, bias=need_bias, pad=pad),
                    bn(num_channels_down),
                    act(act_fun))
        
        self.lat = nn.Sequential(
                    conv(num_channels_down, num_channels_skip, filter_skip_size, bias=need_bias, pad=pad), 
                    bn(num_channels_skip), 
                    act(act_fun))
        
        self.upsample_norm = nn.Sequential(
                        nn.Upsample(scale_factor=2, mode=upsample_mode),
                        nn.BatchNorm2d(num_channels_down, affine=False))
        
        self.dc_conv = nn.Sequential(
                        conv(num_channels_up, num_channels_up, filter_size_up, 1, bias=need_bias, pad=pad),
                        bn(num_channels_up),
                        act(act_fun))
        
        self.dc1 = nn.Sequential(
                    nn.Upsample(scale_factor=2, mode=upsample_mode),
                    conv(num_channels_up, num_channels_up, filter_size_up, 1, bias=need_bias, pad=pad),
                    bn(num_channels_up),
                    act(act_fun))
        
        self.dc_up_conv = nn.Sequential(
                    nn.Upsample(scale_factor=2, mode=upsample_mode),
                    conv(num_channels_skip + num_channels_up, num_channels_up, filter_size_up, 1, bias=need_bias, pad=pad),
                    bn(num_channels_up),
                    act(act_fun))
        
        self.enc_ew0 = nn.Sequential(
                        nn.Conv2d(num_input_channels, num_channels_down, kernel_size=1, stride = 1),
                        bn(num_channels_down), 
                        act(act_fun))
        
        self.output = nn.Sequential(conv(num_channels_up, num_output_channels, 1, bias=need_bias, pad=pad))
        
        
    def forward(self, guide, noise):
        guide_en0 = self.guide_enc(guide)
        guide_en1 = self.enc(guide_en0)
        guide_en2 = self.enc(guide_en1)
        guide_en3 = self.enc(guide_en2)
        guide_en4 = self.enc(guide_en3)
        guide_en5 = self.enc(guide_en4)
        
        guide_dc1 = self.dc1(guide_en5)
        guide_dc2 = self.dc_up_conv(torch.cat((self.lat(guide_en4), guide_dc1), dim=1))
        guide_dc3 = self.dc_up_conv(torch.cat((self.lat(guide_en3), guide_dc2), dim=1))
        guide_dc4 = self.dc_up_conv(torch.cat((self.lat(guide_en2), guide_dc3), dim=1))
        guide_dc5 = self.dc_up_conv(torch.cat((self.lat(guide_en1), guide_dc4), dim=1))
        
        x_en5 = self.enc_ew0(noise)
        x_dc0 = self.FRU(guide_en5, x_en5)
        
        x_dc1 = self.URU(guide_en4, x_dc0)
        x_dc1 = self.dc_conv(x_dc1)
        x_dc1 = self.FRU(guide_dc1, x_dc1)
        
        x_dc2 = self.URU(guide_en3, x_dc1)
        x_dc2 = self.dc_conv(x_dc2)
        x_dc2 = self.FRU(guide_dc2, x_dc2)
        
        x_dc3 =self.URU(guide_en2, x_dc2)
        x_dc3 = self.dc_conv(x_dc3)
        x_dc3 = self.FRU(guide_dc3, x_dc3)
        
        x_dc4 =self.URU(guide_en1, x_dc3)
        x_dc4 = self.dc_conv(x_dc4)
        x_dc4 = self.FRU(guide_dc4, x_dc4)
        
        x_dc5 =self.URU(guide_en0, x_dc4)
        x_dc5 = self.dc_conv(x_dc5)
        x_dc5 = self.FRU(guide_dc5, x_dc5)
        
        out = self.output(x_dc5)
        
        return out