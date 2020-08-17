from os import makedirs
import tensorflow as tf
import numpy as np

from scripts.common import config as cfg, utils
from stable_baselines.common.callbacks import BaseCallback

# save the model everytime when ep_return surpassed a threshold
EP_RETURN_THRES = 250 if not cfg.do_run() \
    else (1000 if cfg.is_mod(cfg.MOD_FLY) else 5000)
MEAN_REW_THRES = 0.05 if not cfg.do_run() else 2.5

class TrainingMonitor(BaseCallback):
    def __init__(self, verbose=0):
        super(TrainingMonitor, self).__init__(verbose)
        # to control how often to save the model
        self.times_surpassed_ep_return_threshold = 0
        self.times_surpassed_mean_reward_threshold = 0
        # log data less frequently
        self.skip_n_steps = 10
        self.skipped_steps = 10

    def _on_training_start(self) -> None:
        self.env = self.training_env

    def _on_step(self) -> bool:
        if cfg.DEBUG and self.num_timesteps > cfg.MAX_DEBUG_STEPS:
            raise SystemExit(f"Planned Exit after {cfg.MAX_DEBUG_STEPS} due to Debugging mode!")

        # skip n steps to reduce logging interval and speed up training
        if self.skipped_steps < self.skip_n_steps:
            self.skipped_steps += 1
            return True

        ep_len = self.get_mean('ep_len_smoothed')
        ep_ret = self.get_mean('ep_ret_smoothed')
        mean_rew = self.get_mean('mean_reward_smoothed')

        self.log_to_tb(mean_rew, ep_len, ep_ret)
        self.save_model_if_good(mean_rew, ep_ret)

        # reset counter of skipped steps after data was logged
        self.skipped_steps = 0

        return True


    def get_mean(self, attribute_name):
        try: return np.mean(self.env.get_attr(attribute_name))
        except: return 0.333

    def log_to_tb(self, mean_rew, ep_len, ep_ret):
        moved_distance = self.get_mean('moved_distance_smooth')
        mean_ep_joint_pow_sum = self.get_mean('mean_ep_joint_pow_sum_normed_smoothed')

        # Log scalar values
        summary = tf.Summary(value=[
            tf.Summary.Value(tag='_own_data/1. moved distance (smoothed 0.25)', simple_value=moved_distance),
            tf.Summary.Value(tag='_own_data/2. step reward (smoothed 0.25)', simple_value=mean_rew),
            tf.Summary.Value(tag='_own_data/3. episode length (smoothed 0.75)', simple_value=ep_len),
            tf.Summary.Value(tag='_own_data/4. episode return (smoothed 0.75)', simple_value=ep_ret),
            tf.Summary.Value(tag='_own_data/5. mean absolute episode joint power (smoothed 0.75)', simple_value=mean_ep_joint_pow_sum)
        ])
        self.locals['writer'].add_summary(summary, self.num_timesteps)


    def save_model_if_good(self, mean_rew, ep_ret):
        if cfg.DEBUG: return
        def get_mio_timesteps():
            return int(self.num_timesteps/1e6)

        ep_ret_thres = 250 + int(EP_RETURN_THRES * (self.times_surpassed_ep_return_threshold + 1))
        if ep_ret > ep_ret_thres:
            utils.save_model(self.model, cfg.save_path,
                             'ep_ret' + str(ep_ret_thres) + f'_{get_mio_timesteps()}M')
            self.times_surpassed_ep_return_threshold += 1
            print(f'Saving model after surpassing EPISODE RETURN of {ep_ret_thres}.')
            print('Model Path: ', cfg.save_path)

        mean_rew_thres = 0.4 + MEAN_REW_THRES * (self.times_surpassed_mean_reward_threshold + 1)
        if mean_rew > (mean_rew_thres):
            utils.save_model(self.model, cfg.save_path,
                             'mean_rew' + str(int(100*mean_rew_thres)) + f'_{get_mio_timesteps()}M')
            self.times_surpassed_mean_reward_threshold += 1
            print(f'Saving model after surpassing MEAN REWARD of {mean_rew_thres}.')
            print('Model Path: ', cfg.save_path)


def _save_rews_n_rets(locals):
    # save all rewards and returns of the training, batch wise
    path_rews = cfg.save_path + 'metrics/train_rews.npy'
    path_rets = cfg.save_path + 'metrics/train_rets.npy'

    try:
        # load already saved rews and rets
        rews = np.load(path_rews)
        rets = np.load(path_rets)
        # combine saved with new rews and rets
        rews = np.concatenate((rews, locals['true_reward']))
        rets = np.concatenate((rets, locals['returns']))
    except Exception:
        rews = locals['true_reward']
        rets = locals['returns']

    # save
    np.save(path_rets, np.float16(rets))
    np.save(path_rews, np.float16(rews))


def callback(_locals, _globals):
    """
    Callback called at each step (for DQN an others) or after n steps (see ACER or PPO2)
    Used to log relevant information during training
    :param _locals: (dict)
    :param _globals: (dict)
    """

    # save all rewards and returns of the training, batch wise
    _save_rews_n_rets(_locals)

    # Log other data about every 200k steps
    # todo: calc as a function of batch for ppo
    #  when updating stable-baselines doesn't provide another option
    #  and check how often TD3 and SAC raise the callback.
    saving_interval = 390 if cfg.use_default_hypers else 6
    n_updates = _locals['update']
    if n_updates % saving_interval == 0:

        model = _locals['self']
        utils.save_pi_weights(model, n_updates)

        # save the model and environment only for every second update (every 400k steps)
        if n_updates % (2*saving_interval) == 0:
            # save model
            model.save(save_path=cfg.save_path + 'models/model_' + str(n_updates))
            # save env
            env_path = cfg.save_path + 'envs/' + 'env_' + str(n_updates)
            makedirs(env_path)
            # save Running mean of observations and reward
            env = model.get_env()
            env.save_running_average(env_path)
            utils.log("Saved model after {} updates".format(n_updates))

    return True