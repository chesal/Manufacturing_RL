# -*- coding: utf-8 -*-
"""
Created on Fri Jul  3 09:18:53 2020

@author: RTS
"""
# import logger
import random
import numpy as np
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers

# tf.config.set_visible_devices([], 'GPU') # Use this to run on CPU only

class Predictron:
    def __init__(self, config):
        # self.inputs = tf.placeholder(tf.float32, shape=[None, config.state_size])
        # self.targets = tf.placeholder(tf.float32, shape=[None, 20])
      
        self.state_size = config.state_size
        self.max_depth = config.max_depth
        
        self.learning_rate = config.learning_rate
        self.beta_1 = config.beta_1
        self.beta_2 = config.beta_2
        self.epsilon = config.epsilon
        self.model = None
      
        # Tensor rewards with shape [batch_size, max_depth + 1]
        self.rewards = None
        # Tensor gammas with shape [batch_size, max_depth + 1]
        self.gammas = None
        # Tensor lambdas with shape [batch_size, max_depth]
        self.lambdas = None
        # Tensor values with shape [batch_size, max_depth + 1]
        self.values = None
        # Tensor  preturns with shape [batch_size, max_depth + 1]
        self.preturns = None
        # Tensor lambda_preturns with shape [batch_size]
        self.lambda_preturns = None
      
        self.build()
    
    def build(self):
        #logger.INFO('Buidling Predictron.')
        self.build_model()
        self.build_loss()
      
        #logger.INFO('Trainable variables:')
        #logger.INFO('*' * 30)
        # for var in tf.trainable_variables():
        #     logger.info(var.op.name)
        #logger.INFO('*' * 30)

    def build_model(self):

        obs = keras.Input(shape=(self.state_size))
        # f_layer1 = layers.Conv2D(32, [3,3], activation='relu',padding="SAME")(obs) # Convolution for spatially correlated inputs
        f_layer1 = layers.Dense(32, activation='relu')(obs) # conv 3x3 stride 1 if spacial correlation in obs
        f_bn1 = layers.BatchNormalization(axis=1)(f_layer1)
        # f_layer2 = layers.Conv2D(32, [3,3], activation='relu',padding="SAME")(f_bn1) # Convolution for spatially correlated inputs
        f_layer2 = layers.Dense(32, activation='relu')(f_bn1) # conv 3x3 stride 1 if spacial correlation in obs
        state = layers.BatchNormalization(axis=1,name='f')(f_layer2)
        
        rewards_arr = []
        gammas_arr = []
        lambdas_arr = []
        values_arr = []
    
        for k in range(self.max_depth):
            state, reward, gamma, lambda_, value = self.core(state)            
            rewards_arr.append(reward)
            gammas_arr.append(gamma)
            lambdas_arr.append(lambda_)
            values_arr.append(value)
    
        _, _, _, _, value = self.core(state)
        # K + 1 elements
        values_arr.append(value)
        
        # [batch_size, K]
        self.rewards = keras.backend.stack(rewards_arr, axis=1)
        print("Rewards:" + str(self.rewards.shape))
        # [batch_size, K]
        self.rewards = layers.Reshape((self.max_depth,))(self.rewards)
        # [batch_size, K + 1]
        self.rewards = layers.Concatenate(axis=1)([keras.backend.zeros(shape=(tf.shape(self.rewards)[0],1), dtype=tf.float32), self.rewards])
    
        # [batch_size, K]
        self.gammas = keras.backend.stack(gammas_arr, axis=1)
        print("Gammas:" + str(self.gammas.shape))
        # [batch_size, K]
        self.gammas = layers.Reshape((self.max_depth,))(self.gammas)
        # [batch_size, K + 1]
        self.gammas = layers.Concatenate(axis=1)([keras.backend.zeros(shape=(tf.shape(self.gammas)[0],1), dtype=tf.float32), self.gammas])

        # [batch_size, K]
        self.lambdas = keras.backend.stack(lambdas_arr, axis=1)
        print("Lambdas:" + str(self.lambdas.shape))
        # [batch_size, K]
        self.lambdas = layers.Reshape((self.max_depth,))(self.lambdas)
    
        # [batch_size, (K + 1)]
        self.values = keras.backend.stack(values_arr, axis=1)
        print("Values:" + str(self.values.shape))
        # [batch_size, K + 1]
        self.values = layers.Reshape((self.max_depth+1,))(self.values)
    
        self.build_preturns()
        self.build_lambda_preturns()
        
        self.model = keras.models.Model(inputs=obs, outputs=[self.g_preturns, self.g_lambda_preturns])
        # self.model.summary()
        # keras.utils.plot_model(self.model, "my_first_model.png", show_shapes=True)
            
    def core(self, state):        
        # State_next
        # net_conv1 = layers.Conv2D(32, [3,3], activation='relu')(state) # Convolution for spatially correlated inputs
        net_fc1 = layers.Dense(32, activation='relu')(state)
        net_bn1 = layers.BatchNormalization(axis=1)(net_fc1)
        
        # net_conv2 = layers.Conv2D(32, [3,3], activation='relu')(net_bn1)
        net_fc2 = layers.Dense(32, activation='relu')(net_bn1)
        net_bn2 = layers.BatchNormalization(axis=1)(net_fc2)
        # net_conv3 = layers.Conv2D(32, [3,3], activation='relu')(net_bn2)
        net_fc3 = layers.Dense(32, activation='relu')(net_bn2)
        net_out = layers.BatchNormalization(axis=1)(net_fc3)
        
        net_flatten = layers.Flatten()(net_bn1) # no effect when fc
        
        # Reward
        reward_net_fc1 = layers.Dense(32, activation='relu')(net_flatten)
        reward_net_bn1 = layers.BatchNormalization(axis=1)(reward_net_fc1)
        reward_net_out = layers.Dense(1)(reward_net_bn1)
        
        # Gamma
        gamma_net_fc1 = layers.Dense(32, activation='relu')(net_flatten)
        gamma_net_bn1 = layers.BatchNormalization(axis=1)(gamma_net_fc1)
        gamma_net_out = layers.Dense(1, activation='sigmoid')(gamma_net_bn1)
        
        # Lambda
        lambda_net_fc1 = layers.Dense(32, activation='relu')(net_flatten)
        lambda_net_bn1 = layers.BatchNormalization(axis=1)(lambda_net_fc1)
        lambda_net_out = layers.Dense(1, activation='sigmoid')(lambda_net_bn1)
        
        # Value
        value_net_fc1 = layers.Dense(32, activation='relu')(layers.Flatten()(state))
        value_net_bn1 = layers.BatchNormalization(axis=1)(value_net_fc1)
        value_net_out = layers.Dense(1)(value_net_bn1)
    
        return net_out, reward_net_out, gamma_net_out, lambda_net_out, value_net_out
    
    def build_preturns(self):
        ''' Eqn (2) '''
      
        g_preturns = []
        # for k = 0, g_0 = v[0], still fits.
        for k in range(self.max_depth, -1, -1):
            g_k = self.values[:, k]
            for kk in range(k, 0, -1):
                g_k = self.rewards[:, kk] + self.gammas[:, kk] * g_k
            g_preturns.append(g_k)
        # reverse to make 0...K from K...0
        g_preturns = g_preturns[::-1]
        self.g_preturns = keras.backend.stack(g_preturns, axis=1)
        self.g_preturns = layers.Reshape((self.max_depth+1,))(self.g_preturns)
    
    def build_lambda_preturns(self):
        ''' Eqn (4) '''
        g_k = self.values[:, -1]
        for k in range(self.max_depth - 1, -1, -1):
            g_k = (1 - self.lambdas[:, k]) * self.values[:, k] + \
                self.lambdas[:, k] * (self.rewards[:, k + 1] + self.gammas[:, k + 1] * g_k)
        self.g_lambda_preturns = g_k

    def build_loss(self):
        self.model.compile(
            optimizer = keras.optimizers.Adam(learning_rate=self.learning_rate, beta_1 = self.beta_1, beta_2=self.beta_2, epsilon=self.epsilon),
            loss = [keras.losses.MeanSquaredError(), keras.losses.MeanSquaredError()]
            )
        # Loss Eqn (5)
        # self.loss_preturns = keras.losses.mean_squared_error(self.g_preturns, self.targets, scope='preturns')
        # keras.losses.add_loss(self.loss_preturns)
        # tf.summary.scalar('loss_preturns', self.loss_preturns)
        # # Loss Eqn (7)
        # self.loss_lambda_preturns = keras.losses.mean_squared_error(
        #   self.g_lambda_preturns, self.targets, scope='lambda_preturns')
        # keras.losses.add_loss(self.loss_lambda_preturns)
        # tf.summary.scalar('loss_lambda_preturns', self.loss_lambda_preturns)
        # self.total_loss = keras.losses.get_total_loss(name='total_loss')
        
class Replay_buffer:
    def __init__(self, memory_size = 10000):
        assert(memory_size > 0)
        self.memory = list([])
        self.memory_size = memory_size
    
    def put(self, data):
        if len(self.memory) < self.memory_size:
            self.memory.append(data)
        else:
            while(len(self.memory) >= self.memory_size):
                self.memory.pop(0)
            self.memory.append(data)
    
    def get(self, batch_size=1):
        if len(self.memory) >= batch_size:
            data = random.sample(self.memory, batch_size)
        else: 
            data = []
            print("Replay_buffer empty")
        return data