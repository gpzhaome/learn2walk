import numpy as np
from os.path import dirname
from tensorflow import keras
from tensorflow.keras import layers
from matplotlib import pyplot as plt

from sklearn.model_selection import train_test_split
from scripts.behavior_cloning.dataset import get_obs_and_delta_actions

from scripts.common import config as cfg

SAVE_MODEL = False
FLY = True
SHUFFLE = True
EPOCHS = 200
LEARN_RATE0 = 0.01
LEARN_RATE1 = 0.0005

def build_model(state_dim, act_dim):
    model = keras.Sequential()
    model.add(keras.Input(shape=(state_dim,), name='input'))
    l2_coeff = 0.0005
    for i, hid_size in enumerate(cfg.hid_layer_sizes_pi):
        model.add(layers.Dense(hid_size, activation='relu', name=f'hid{i+1}',
                               kernel_initializer=keras.initializers.Orthogonal(gain=0.01),
                               kernel_regularizer=keras.regularizers.l2(l=l2_coeff)))
    model.add(layers.Dense(act_dim, activation='linear', name='output',
                           kernel_initializer=keras.initializers.Orthogonal(gain=0.01),
                           kernel_regularizer=keras.regularizers.l2(l=l2_coeff)))
    model.summary()
    return model

if __name__ == '__main__':
    x_data, y_data = get_obs_and_delta_actions(norm_obs=True, norm_acts=True, fly=FLY)
    y_data = np.zeros_like(y_data)

    # train, val, test split
    x_train, x_test, y_train, y_test = \
        train_test_split(x_data, y_data, test_size=0.2, shuffle=SHUFFLE)
    x_val, x_test, y_val, y_test = \
        train_test_split(x_test, y_test, test_size=0.5, shuffle=SHUFFLE)

    # check sizes
    print('X train, val, test sizes: ', x_train.shape, x_val.shape, x_test.shape)
    print('Y train, val, test sizes: ', y_train.shape, y_val.shape, y_test.shape)

    # check shuffling
    if SHUFFLE and False:
        plt.plot(x_train[:500, [3,6,9]])
        plt.show()

    # build model
    model = build_model(x_train.shape[1], y_train.shape[1])

    # compile model
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=LEARN_RATE0),
        # Loss function to minimize
        loss='mean_absolute_error',
        # List of metrics to monitor
        metrics=[keras.metrics.MeanSquaredError(),
                 keras.metrics.MeanSquaredLogarithmicError(),
                 keras.metrics.MeanAbsoluteError(),
                 keras.metrics.MeanAbsolutePercentageError()],
    )

    # construct save paths
    model_path = dirname(dirname(dirname(__file__))) \
                 + '/models/behav_clone/models/'
    model_name = 'ZERO_MAE_const_ortho_l2_actnorm' \
                 + ('FLY' if FLY else '') + f'_ep{EPOCHS}'

    # create callback to save best model
    best_model_path = model_path + f'best/{model_name}'
    save_best_callback = keras.callbacks.ModelCheckpoint(
        best_model_path, save_best_only=True,
        monitor='val_loss', mode='min')

    # learning rate schedule (linear)
    def linear_lr_schedule(epoch):
        return LEARN_RATE0 + (LEARN_RATE1-LEARN_RATE0)/EPOCHS * epoch

    lr_decay_callback = keras.callbacks.LearningRateScheduler(linear_lr_schedule)

    # train model
    history = model.fit(x_train, y_train, epochs=EPOCHS, verbose=1,
                        validation_data=(x_val, y_val),
                        callbacks=[save_best_callback, lr_decay_callback])

    # evaluate the model
    train_metrics = model.evaluate(x_train, y_train, verbose=0)
    test_metrics = model.evaluate(x_test, y_test, verbose=0)
    print('MAE:\nTrain: %.5f, Test: %.5f\n' % (train_metrics[0], test_metrics[0]))
    # plot loss during training
    losses = ['loss',  'mean_squared_error', 'mean_squared_logarithmic_error',
              'mean_absolute_error', 'mean_absolute_percentage_error']

    if SAVE_MODEL:
        # save weights of best model
        best_model = keras.models.load_model(best_model_path)
        best_model_weights_path = best_model_path.replace('best', 'weights')
        best_model.save_weights(best_model_weights_path+'.h5')
        print('Saved weights of best model in:\n', best_model_weights_path)

    for i, loss_str in enumerate(losses):
        plt.subplot(2, len(losses)//2+1, i+1)
        plt.title(str.capitalize(loss_str))
        plt.plot(history.history[loss_str], label='train')
        plt.plot(history.history['val_'+loss_str], label='validation')
    plt.legend()
    plt.show()


