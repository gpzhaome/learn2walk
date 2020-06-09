'''
Interface for environments using reference trajectories.
'''
import gym, mujoco_py
import numpy as np
from scripts.common.ref_trajecs import ReferenceTrajectories as RefTrajecs


# Workaround: MujocoEnv calls step() before calling reset()
# Then, RSI is not executed yet and ET gets triggered during step()
_rsinitialized = False

class MimicEnv:
    def __init__(self: gym.Env, ref_trajecs:RefTrajecs):
        '''@param: self: gym environment implementing the MimicEnv interface.'''
        self.refs = ref_trajecs
        # adjust simulation properties to the frequency of the ref trajec
        self.model.opt.timestep = 1e-3
        self.frame_skip = 5

    def step(self):
        global _rsinitialized
        if _rsinitialized:
            self.refs.next()

    def get_joint_kinematics(self, exclude_com=False):
        '''Returns qpos and qvel of the agent.'''
        qpos = np.copy(self.sim.data.qpos)
        qvel = np.copy(self.sim.data.qvel)
        if exclude_com:
            qpos = self._remove_by_indices(qpos, self._get_COM_indices())
            qvel = self._remove_by_indices(qvel, self._get_COM_indices())
        return qpos, qvel

    def get_qpos(self):
        return np.copy(self.sim.data.qpos)

    def playback_ref_trajectories(self, timesteps=2000):
        self.reset()
        sim = self.sim
        for i in range(timesteps):
            old_state = sim.get_state()
            new_state = mujoco_py.MjSimState(old_state.time,
                                             self.refs.get_qpos(i),
                                             self.refs.get_qvel(i),
                                             old_state.act, old_state.udd_state)
            sim.set_state(new_state)
            # self.step(np.zeros_like(self.action_space.sample()))
            sim.forward()
            self.render()

        self.close()
        raise SystemExit('Environment intentionally closed after playing back trajectories.')


    def _get_obs(self):
        global _rsinitialized
        qpos, qvel = self.get_joint_kinematics()
        if _rsinitialized:
            desired_walking_speed = self.refs.get_step_velocity()
        else:
            desired_walking_speed = -3.33
        obs = np.concatenate([np.array([desired_walking_speed]), qpos, qvel]).ravel()
        return obs

    def reset_model(self):
        '''WARNING: This method seems to be specific to MujocoEnv.
           Other gym environments just use reset().'''
        qpos, qvel = self.get_random_init_state()
        self.set_state(qpos, qvel)
        rew = self.get_imitation_reward()
        assert rew > 0.5, "Reward should be at least 0.5 after RSI!"
        assert not self.has_exceeded_allowed_deviations()
        return self._get_obs()


    def get_random_init_state(self):
        ''' Random State Initialization:
            @returns: qpos and qvel of a random step at a random position'''
        global _rsinitialized
        _rsinitialized = True
        return self.refs.get_random_init_state()


    def get_ref_kinematics(self, exclude_com=False):
        qpos, qvel = self.refs.get_ref_kinmeatics()
        if exclude_com:
            qpos = self._remove_by_indices(qpos, self._get_COM_indices())
            qvel = self._remove_by_indices(qvel, self._get_COM_indices())
        return qpos, qvel


    def get_pose_reward(self):
        # get sim and ref joint positions excluding com position
        qpos, _ = self.get_joint_kinematics(exclude_com=True)
        ref_pos, _ = self.get_ref_kinematics(exclude_com=True)
        dif = qpos - ref_pos
        dif_sqrd = np.square(dif)
        sum = np.sum(dif_sqrd)
        pose_rew = np.exp(-2 * sum)
        return pose_rew

    def get_vel_reward(self):
        _, qvel = self.get_joint_kinematics(exclude_com=True)
        _, ref_vel = self.get_ref_kinematics(exclude_com=True)
        dif = qvel - ref_vel
        dif_sqrd = np.square(dif)
        sum = np.sum(dif_sqrd)
        vel_rew = np.exp(-0.1 * sum)
        return vel_rew

    def get_com_reward(self):
        qpos, qvel = self.get_joint_kinematics()
        ref_pos, ref_vel = self.get_ref_kinematics()
        com_is = self._get_COM_indices()
        com_pos, com_ref = qpos[com_is], ref_pos[com_is]
        dif = com_is - com_ref
        dif_sqrd = np.square(dif)
        sum = np.sum(dif_sqrd)
        com_rew = np.exp(-10 * sum)
        return com_rew

    def _remove_by_indices(self, list, indices):
        """
        Removes specified indices from the passed list and returns it.
        """
        new_list = [item for i, item in enumerate(list) if i not in indices]
        return np.array(new_list)

    def get_imitation_reward(self):
        global _rsinitialized
        if not _rsinitialized:
            return -3.33
        # todo: do we need the end-effector reward?
        w_pos, w_vel, w_com = 0.7, 0.15, 0.15
        pos_rew = self.get_pose_reward()
        vel_ref = self.get_vel_reward()
        com_rew = self.get_com_reward()
        imit_rew = w_pos * pos_rew + w_vel * vel_ref + w_com * com_rew
        return imit_rew

    def do_terminate_early(self, rew, com_height, trunk_ang_saggit,
                           rew_threshold = 0.05):
        """
        Early Termination based on reward, falling and episode duration
        """
        if not _rsinitialized:
            # ET only works after RSI was executed
            return False

        # calculate if allowed com height was exceeded (e.g. walker felt down)
        com_height_des = self.refs.get_com_height()
        com_delta = np.abs(com_height_des - com_height)
        com_deviation_prct = com_delta/com_height_des
        allowed_com_deviation_prct = 0.4
        com_max_dev_exceeded = com_deviation_prct > allowed_com_deviation_prct

        # calculate if trunk angle exceeded limits of 45° (0.785 in rad)
        trunk_ang_exceeded = np.abs(trunk_ang_saggit) > 0.7

        rew_too_low = rew < rew_threshold
        max_episode_dur_reached = self.refs.ep_dur > 1000
        return com_max_dev_exceeded or trunk_ang_exceeded or rew_too_low or max_episode_dur_reached

    def has_exceeded_allowed_deviations(self, max_dev_pos=0.5, max_dev_vel=2):
        '''Early Termination based on trajectory deviations:
           @returns: True if qpos and qvel have deviated
           too much from the reference trajectories.
           @params: max_dev_x are both percentages of maximum range
                    of the corresponding joint ref trajectories.'''

        if not _rsinitialized:
            # ET only works after RSI was executed
            return False

        qpos, qvel = self.get_joint_kinematics()
        ref_qpos, ref_qvel = self.get_ref_kinematics()
        pos_ranges, vel_ranges = self.refs.get_kinematic_ranges()
        # increase trunk y rotation range
        pos_ranges[2] *= 5
        vel_ranges[2] *= 5
        delta_pos = np.abs(ref_qpos - qpos)
        delta_vel = np.abs(ref_qvel - qvel)

        # was the maximum allowed deviation exceeded
        pos_exceeded = delta_pos > max_dev_pos * pos_ranges
        vel_exceeded = delta_vel > max_dev_vel * vel_ranges

        # investigate deviations:
        # which kinematics have exceeded the allowed deviations
        pos_is = np.where(pos_exceeded==True)[0]
        vel_is = np.where(vel_exceeded==True)[0]
        pos_labels, vel_labels = self.refs.get_labels_by_index(pos_is, vel_is)

        DEBUG_ET = False
        if DEBUG_ET and (pos_is.any() or vel_is.any()):
            print()
            for i_pos, pos_label in zip(pos_is, pos_labels):
                print(f"{pos_label} \t exceeded the allowed deviation ({int(100*max_dev_pos)}% "
                      f"of the max range of {pos_ranges[i_pos]}) after {self.refs.ep_dur} steps:"
                      f"{delta_pos[i_pos]}")

            print()
            for i_vel, vel_label in zip(vel_is, vel_labels):
                print(f"{vel_label} \t exceeded the allowed deviation ({int(100*max_dev_vel)}% "
                      f"of the max range of {vel_ranges[i_vel]}) after {self.refs.ep_dur} steps:"
                      f"{delta_vel[i_vel]}")

        return pos_exceeded.any() or vel_exceeded.any()

    # ----------------------------
    # Methods we override:
    # ----------------------------

    def close(self):
        # overwritten to set RSI init flag to False
        global _rsinitialized
        _rsinitialized = False
        # calls MujocoEnv.close()
        super().close()

    # ----------------------------
    # Methods to override:
    # ----------------------------

    def _get_COM_indices(self):
        """
        Needed to distinguish between joint and COM kinematics.

        Returns a list of indices pointing at COM joint position/index
        in the considered robot model, e.g. [0,1,2]
        """
        raise NotImplementedError