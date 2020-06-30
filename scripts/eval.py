import os.path
import numpy as np
from scripts.common import utils
from scripts.common import config as cfg
from gym_mimic_envs.monitor import Monitor as EnvMonitor

# to decrease the amount of deprecation warnings
import tensorflow as tf
tf.logging.set_verbosity(tf.logging.ERROR)

from stable_baselines import PPO2
plt = utils.import_pyplot()


RENDER = True and not utils.is_remote()
NO_ET = True
PLOT_RESULTS = False

FROM_PATH = True
PATH = "/mnt/88E4BD3EE4BD2EF6/Masters/M.Sc. Thesis/Code/models/deepmim/" \
       "real_torque/mim_walker2d/1envs/ppo2/hyper_dflt/10mio/pun100_nstp4096_gamma999/299"
if not PATH.endswith('/'): PATH += '/'

# which model should be evaluated
run_id = 78
checkpoint = 999

# evaluate for n episodes
n_eps = 25
# how many actions to record in each episode
rec_n_steps = 1000

def eval_model(from_config=True):
    """@:param from_config: if true, reloads the run_id from config file
                before evaluation (for direct eval after training).
                If false, uses the id specified in this script. """

    print('\n---------------------------\n'
              'MODEL EVALUATION STARTED'
          '\n---------------------------\n')

    global run_id, checkpoint

    # get model location from the config file
    if from_config:
        run_id = cfg.run
        checkpoint = cfg.final_checkpoint

    # change save_path to specified model
    if FROM_PATH:
        save_path = PATH
    else:
        save_path = cfg.save_path_norun + f'{run_id}/'


    # load model
    model_path = save_path + f'models/model_{checkpoint}.zip'
    model = PPO2.load(load_path=model_path)

    print('\nModel:\n', model_path + '\n')

    env = load_env(checkpoint, save_path)
    env = EnvMonitor(env, True)

    ep_rewards, all_returns, ep_durations = [], [], []
    all_rewards = np.zeros((n_eps, rec_n_steps))
    all_actions = np.zeros((n_eps, env.action_space.shape[0], rec_n_steps))

    ep_count, ep_dur = 0, 0
    obs = env.reset()

    if not RENDER: print('Episodes finished:\n0 ', end='')

    while True:
        ep_dur += 1
        action, hid_states = model.predict(obs, deterministic=False)
        if ep_dur <= rec_n_steps:
            all_actions[ep_count, :, ep_dur - 1] = action
        obs, reward, done, info = env.step(action)
        ep_rewards += [reward[0] if isinstance(reward,list) else reward]
        done_is_scalar = isinstance(done, bool) or \
                         isinstance(done, np.bool_) or isinstance(done, np.bool)
        done_is_list = isinstance(done, list)
        done = (done_is_scalar and done) or (done_is_list and done.any())
        # end the episode also after a max amount of steps
        done = done or (ep_dur > 2000)
        if done:
            ep_durations.append(ep_dur)
            # clip ep_dur to max number of steps to save
            ep_dur = min(ep_dur, rec_n_steps)
            all_rewards[ep_count,:ep_dur] = np.asarray(ep_rewards)[:ep_dur]
            ep_return = np.sum(ep_rewards)
            all_returns.append(ep_return)
            if RENDER: print('ep_return: ', ep_return)
            # reset all episode specific containers and counters
            ep_rewards = []
            ep_dur = 0
            ep_count += 1
            # stop evaluation after enough episodes were observed
            if ep_count >= n_eps: break
            elif ep_count % 5 == 0:
                print(f'-> {ep_count}', end=' ', flush=True)
            env.reset()

        if RENDER: env.render()
    env.close()

    mean_return = np.mean(all_returns)
    print('\n\nAverage episode return was: ', mean_return)

    # create the metrics folder
    metrics_path = save_path + f'metrics/model_{checkpoint}/'
    os.makedirs(metrics_path, exist_ok=True)

    np.save(metrics_path + '/{}_mean_ret_on_{}eps'.format(int(mean_return), n_eps), mean_return)
    np.save(metrics_path + '/rewards', all_rewards)
    np.save(metrics_path + '/actions', all_actions)
    np.save(metrics_path + '/ep_returns', all_returns)

    # count and save number of parameters in the model
    num_policy_params = np.sum([np.prod(tensor.get_shape().as_list())
                                for tensor in model.params if 'pi' in tensor.name])
    num_valfunc_params = np.sum([np.prod(tensor.get_shape().as_list())
                                for tensor in model.params if 'vf' in tensor.name])
    num_params = np.sum([np.prod(tensor.get_shape().as_list())
                         for tensor in model.params])

    count_params_dict = {'n_pi_params': num_policy_params, 'n_vf_params':num_valfunc_params,
                         'n_params': num_params}

    np.save(metrics_path + '/weights_count', count_params_dict)
    print(count_params_dict)

    # mark special episodes
    ep_best = np.argmax(all_returns)
    ep_worst = np.argmin(all_returns)
    ep_average = np.argmin(np.abs(all_returns - mean_return))
    relevant_eps = [ep_best, ep_worst, ep_average]

    if PLOT_RESULTS:
        plt.plot(all_returns)
        plt.plot(np.arange(len(all_returns)),
                 np.ones_like(all_returns)*mean_return, '--')
        plt.vlines(relevant_eps, ymin=min(all_returns), ymax=max(all_returns),
                   colors='#cccccc', linestyles='dashed')
        plt.title(f"Returns of {n_eps} epochs")
        plt.show()

    record_video(model, checkpoint, all_returns, relevant_eps)


def record_video(model, checkpoint, all_returns, relevant_eps):
    """ GENERATE VIDEOS of different performances (best, worst, mean)

    # The idea is to understand the agent by observing his behavior
    # during the best, worst episode and an episode with a close to average return.
    # Therefore, we reload the environment to have same behavior as in the evaluation episodes
    # and record the video only for the interesting episodes.
    """

    # import the video recorder
    from stable_baselines.common.vec_env import VecVideoRecorder

    utils.log("Preparing video recording!")

    # which episodes are interesting to record a video of
    relevant_eps_returns = [max(all_returns), min(all_returns), np.mean(all_returns)]
    relevant_eps_names = ['best', 'worst', 'mean']

    # reload environment to replicate behavior of evaluation episodes (determinism tested)
    if FROM_PATH:
        save_path = PATH
    else:
        save_path = cfg.save_path_norun + f'{run_id}/'
    env = load_env(checkpoint, save_path)
    obs = env.reset()

    ep_count, step = 0, 0

    # determine video duration
    fps = env.venv.metadata['video.frames_per_second']
    video_len_secs = 10
    video_len = video_len_secs * fps

    # if epoch is not interesting, choose a bad action to finish it quickly
    zero_actions = np.zeros_like(model.action_space.high)

    # repeat only as much episodes as necessary
    while ep_count <= max(relevant_eps):

        if ep_count in relevant_eps:
            ep_index = relevant_eps.index(ep_count)
            ep_ret = relevant_eps_returns[ep_index]
            ep_name = relevant_eps_names[ep_index]

            # create an environment that captures performance on video
            video_env = VecVideoRecorder(env, save_path + 'videos',
                                         record_video_trigger=lambda x: x > 0,
                                         video_length=video_len,
                                         name_prefix=f'{ep_name}_{int(ep_ret)}_')
            if 'fly' in save_path:
                video_env.env.venv.envs[0].env._FLY = True
                print('flight detected')
            obs = video_env.reset()


            while step <= rec_n_steps:
                action, hid_states = model.predict(obs, deterministic=False)
                obs, reward, done, info = video_env.step(action)
                step += 1
                # only reset when agent has fallen
                if has_fallen(video_env):
                    video_env.reset()



            video_env.close()
            utils.log(f"Saved performance video after {step} steps.")
            step = 0

        # irrelevant episode, finish as quickly as possible
        else:
            # reset the environment to init RSI and ET
            env.reset()
            while True:
                action = zero_actions
                obs, reward, done, info = env.step(action)
                if done.any(): break

        # log progress
        if ep_count % 10 == 0:
            print(f'{ep_count} episodes finished', flush=True)

        ep_count += 1
    env.close()

def has_fallen(video_env):
    com_z_pos = video_env.env.venv.envs[0].env.data.qpos[1]
    return com_z_pos < 0.5

def load_env(checkpoint, save_path):
    # load a single environment for evaluation
    # todo: we could also use multiple envs to speedup eval
    env = utils.vec_env(cfg.env_id, num_envs=1, norm_rew=False)
    # set the calculated running means for obs and rets
    env.load_running_average(save_path + f'envs/env_{checkpoint}')
    return env


if __name__ == "__main__":
    eval_model(from_config=False)

# eval.py was called from another script
else:
    RENDER = False
    FROM_PATH = False