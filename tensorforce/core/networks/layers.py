# Copyright 2017 reinforce.io. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

"""
Creates various neural network layers. For most layers, these functions use
TF-slim layer types. The purpose of this class is to encapsulate
layer types to mix between layers available in TF-slim and custom implementations.
"""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import division

from collections import Counter
import json
from math import sqrt
import os

import numpy as np
import tensorflow as tf

from tensorforce import TensorForceError, util


def flatten(x, scope='flatten', summary_level=0):
    """Flatten layer.

    Args:
        x: Input tensor

    Returns: Input tensor reshaped to 1d tensor

    """
    with tf.variable_scope(scope):
        x = tf.reshape(tensor=x, shape=(-1, util.prod(x.get_shape().as_list()[1:])))

    return x


def nonlinearity(x, name='relu', scope='nonlinearity', summary_level=0):
    """ Applies a non-linearity to an input and returns the result.

    Args:
        x: Input tensor
        name: String identifier of non-linearity. Options: elu, relu, selu, sigmoid,
        softmax, softplus, tanh

    Returns:

    """
    with tf.variable_scope(scope):
        if name == 'elu':
            x = tf.nn.elu(features=x)
        elif name == 'relu':
            x = tf.nn.relu(features=x)
            if summary_level >= 3:  # summary level 3: layer activations
                non_zero_pct = (tf.cast(tf.count_nonzero(x), tf.float32) / tf.cast(tf.reduce_prod(tf.shape(x)), tf.float32))
                tf.summary.scalar('relu-sparsity', 1.0 - non_zero_pct)
        elif name == 'selu':
            # https://arxiv.org/pdf/1706.02515.pdf
            alpha = 1.6732632423543772848170429916717
            scale = 1.0507009873554804934193349852946
            negative = alpha * tf.nn.elu(features=x)
            x = scale * tf.where(condition=(x >= 0.0), x=x, y=negative)
        elif name == 'sigmoid':
            x = tf.sigmoid(x=x)
        elif name == 'softmax':
            x = tf.nn.softmax(logits=x)
        elif name == 'softplus':
            x = tf.nn.softplus(features=x)
        elif name == 'tanh':
            x = tf.nn.tanh(x=x)
        else:
            raise TensorForceError('Invalid non-linearity: {}'.format(name))

    return x


def linear(x, size, weights=None, bias=True, l2_regularization=0.0, scope='linear', summary_level=0):
    """
    Linear layer.

    Args:
        x: Input tensor. Must be rank 2
        size: Neurons in layer
        weights: None for random matrix, otherwise given float or array is used.
        bias: Bool to indicate whether bias is used, otherwise given float or array is used.
        l2_regularization: L2-regularisation value
        weights: Weights for layer. If none, initialisation defaults to Xavier (normal with
        size/shape dependent standard deviation).

    Returns:

    """
    input_rank = util.rank(x)
    if input_rank != 2:
        raise TensorForceError('Invalid input rank for linear layer: {},'
                               ' must be 2.'.format(input_rank))

    with tf.variable_scope(scope):
        shape = (x.shape[1].value, size)
        weights_variable = True
        if weights is None:
            stddev = min(0.1, sqrt(2.0 / (x.shape[1].value + size)))
            weights = tf.random_normal(shape=shape, stddev=stddev)
        elif isinstance(weights, tf.Tensor):
            weights_variable = False
            if util.shape(weights) != shape:
                raise TensorForceError('Weights shape {} does not match expected shape {} '
                                       .format(weights.shape, shape))
        elif isinstance(weights, float):
            weights = np.full(shape, weights, dtype=np.float32)
        else:
            weights = np.asarray(weights, dtype=np.float32)
            if weights.shape != shape:
                raise TensorForceError('Weights shape {} does not match expected shape {} '
                                       .format(weights.shape, shape))

        shape = (size,)
        bias_variable = True
        if isinstance(bias, bool):
            bias = tf.zeros(shape=shape) if bias else None
        elif isinstance(bias, tf.Tensor):
            bias_variable = False
            if util.shape(bias) != shape:
                raise TensorForceError('Bias shape {} does not match expected shape {} '
                                       .format(bias.shape, shape))
        elif isinstance(bias, float):
            bias = np.full(shape, bias, dtype=np.float32)
        else:
            bias = np.asarray(bias, dtype=np.float32)
            if bias.shape != shape:
                raise TensorForceError('Bias shape {} does not match expected shape {} '
                                       .format(bias.shape, shape))

        if weights_variable:
            weights = tf.Variable(initial_value=weights, dtype=tf.float32, name='W')
            if l2_regularization > 0.0:
                tf.losses.add_loss(l2_regularization * tf.nn.l2_loss(t=weights))

        x = tf.matmul(a=x, b=weights)

        if bias is not None:
            if bias_variable:
                bias = tf.Variable(initial_value=bias, dtype=tf.float32, name='b')
                if l2_regularization > 0.0:
                    tf.losses.add_loss(l2_regularization * tf.nn.l2_loss(t=bias))
            x = tf.nn.bias_add(value=x, bias=bias)

    return x


def dense(x, size, bias=True, activation='relu', l2_regularization=0.0, scope='dense', summary_level=0):
    """
    Fully connected layer.

    Args:
        x: Input tensor
        size: Neurons in layer
        bias: Bool, indicates whether bias is used
        activation: Non-linearity type, defaults to relu
        l2_regularization: L2-regularisation value

    Returns:

    """
    input_rank = util.rank(x)
    if input_rank != 2:
        raise TensorForceError('Invalid input rank for linear layer: {},'
                               ' must be 2.'.format(input_rank))

    with tf.variable_scope(scope):
        x = linear(x=x, size=size, bias=bias, l2_regularization=l2_regularization)
        x = nonlinearity(x=x, name=activation, summary_level=summary_level)

        if summary_level >= 3:
            tf.summary.histogram('activations', x)
    return x


def conv2d(x, size, window=3, stride=1, padding='SAME', bias=False, activation='relu',
           l2_regularization=0.0, scope='conv2d', summary_level=0):
    """A 2d convolutional layer.

    Args:
        x: Input tensor. Must be rank 4
        size: Neurons
        window: Filter window size
        stride: Filter stride
        padding: One of [VALID, SAME]
        bias: Bool, indicates whether bias is used
        activation: Non-linearity type, defaults to relu
        l2_regularization: L2-regularisation value

    Returns:

    """
    input_rank = util.rank(x)
    if input_rank != 4:
        raise TensorForceError('Invalid input rank for conv2d layer: {}, must be 4'.format(input_rank))

    with tf.variable_scope(scope):
        shape = (window, window, x.shape[3].value, size)
        stddev = min(0.1, sqrt(2.0 / size))
        filters = tf.Variable(initial_value=tf.random_normal(shape=shape, stddev=stddev), name='W')

        if l2_regularization > 0.0:
            tf.losses.add_loss(l2_regularization * tf.nn.l2_loss(t=filters))

        strides = (1, stride, stride, 1)
        x = tf.nn.conv2d(input=x, filter=filters, strides=strides, padding=padding)

        if bias:
            bias = tf.Variable(initial_value=tf.zeros(shape=(size,)), name='b')
            if l2_regularization > 0.0:
                tf.losses.add_loss(l2_regularization * tf.nn.l2_loss(t=bias))
            x = tf.nn.bias_add(value=x, bias=bias)

        x = nonlinearity(x=x, name=activation, summary_level=summary_level)

        if summary_level >= 3:
            tf.summary.histogram('activations', x)
    return x


def lstm(x, size=None, dropout=None, scope='lstm', summary_level=0):
    """

    Args:
        x: Input tensor.
        size: Layer size, defaults to input size.
        dropout: dropout_keep_prob (eg 0.5) for regularization, applied via rnn.DropoutWrapper

    Returns:

    """
    input_rank = util.rank(x)
    if input_rank != 2:
        raise TensorForceError('Invalid input rank for lstm layer: {},'
                               ' must be 2.'.format(input_rank))
    if not size:
        size = x.get_shape()[1].value

    with tf.variable_scope(scope):
        internal_input = tf.placeholder(dtype=tf.float32, shape=(None, 2, size))
        lstm_cell = tf.contrib.rnn.LSTMCell(num_units=size)
        if dropout:
            lstm_cell = tf.contrib.rnn.DropoutWrapper(lstm_cell, output_keep_prob=dropout)
        c = internal_input[:, 0, :]
        h = internal_input[:, 1, :]
        state = tf.contrib.rnn.LSTMStateTuple(c=c, h=h)
        x, state = lstm_cell(inputs=x, state=state)

        internal_output = tf.stack(values=(state.c, state.h), axis=1)
        internal_init = np.zeros(shape=(2, size))

        if summary_level >= 3:
            tf.summary.histogram('activations', x)
    return x, (internal_input,), (internal_output,), (internal_init,)


layers = {
    'flatten': flatten,
    'nonlinearity': nonlinearity,
    'linear': linear,
    'dense': dense,
    'conv2d': conv2d,
    'lstm': lstm
}


def layered_network_builder(layers_config):
    """Returns a function defining a layered neural network according to the given configuration.


    Args:
        layers_config: Iterable of layer configuration dicts.

    Returns:

    """

    def network_builder(inputs, summary_level=0):
        input_length = len(inputs)

        if input_length != 1:
            raise TensorForceError('Layered network must have only one input,'
                                   ' input length {} given.'.format(input_length))
        x = next(iter(inputs.values()))
        internal_inputs = []
        internal_outputs = []
        internal_inits = []

        layer_counter = Counter()
        for layer_config in layers_config:
            if callable(layer_config['type']):
                scope = layer_config['type'].__name__ + str(layer_counter[layer_config['type']])
            else:
                scope = layer_config['type'] + str(layer_counter[layer_config['type']])

            x = util.get_object(
                obj=layer_config,
                predefined=layers,
                kwargs=dict(x=x, scope=scope, summary_level=summary_level)
            )
            layer_counter[layer_config['type']] += 1
            if isinstance(x, list) or isinstance(x, tuple):
                assert len(x) == 4
                internal_inputs.extend(x[1])
                internal_outputs.extend(x[2])
                internal_inits.extend(x[3])
                x = x[0]

        if internal_inputs:
            return x, internal_inputs, internal_outputs, internal_inits
        else:
            return x

    return network_builder


def from_json(filename):
    """Creates a layer_networkd_builder from a JSON.

    Args:
        filename: Path to configuration

    Returns: A layered_network_builder function with layers generated from the JSON

    """
    path = os.path.join(os.getcwd(), filename)
    with open(path, 'r') as fp:
        config = json.load(fp=fp)

    return layered_network_builder(config)
