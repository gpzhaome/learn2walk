import numpy as np
import scipy.io as spio
from scripts.common import utils

plt = utils.config_pyplot(font_size=12, tick_size=12)

# load matlab data, containing trajectories of 250 steps
data = spio.loadmat('/mnt/88E4BD3EE4BD2EF6/Masters/M.Sc. Thesis/Code/'
                    'assets/ref_trajecs/Traj_Ramp_Slow_final.mat')

# 250 steps, shape (250,1), where 1 is an array with kinematic data
data = data['Data']
# flatten the array to have dim (steps,)
data = data.flatten()

# first step (37 dims, 281 timesteps)
step = data[0]
dofs, timesteps = step.shape

def get_com_pos_all_steps():
    com_pos = []
    for step in range(len(data)):
        com_pos.extend(data[step][0])
    return com_pos

com_pos_all = get_com_pos_all_steps()
plt.plot(com_pos_all)
plt.show()

test_refs = False
if test_refs:
    from scripts.common.ref_trajecs import ReferenceTrajectories as RT

    rt = RT('/mnt/88E4BD3EE4BD2EF6/Masters/M.Sc. Thesis/Code/'
                        'assets/ref_trajecs/Traj_Ramp_Slow_final.mat')
    rt.step = rt.data[0]
    compos, comvel = rt.get_com_kinematics()
    step[0:3,:] -= compos

# label every trajectory with the corresponding name
labels = ['COM Pos (X)', 'COM Pos (Y)', 'COM Pos (Z)',
          'Trunk Rot (quat1)', 'Trunk Rot (quat2)', 'Trunk Rot (quat3)', 'Trunk Rot (quat4)',
          'Ang Hip Frontal R', 'Ang Hip Sagittal R',
          'Ang Knee R', 'Ang Ankle R',
          'Ang Hip Frontal L', 'Ang Hip Sagittal L',
          'Ang Knee L', 'Ang Ankle L',

          'COM Vel (X)', 'COM Vel (Y)', 'COM Vel (Z)',
          'Trunk Ang Vel (X)', 'Trunk Ang Vel (Y)', 'Trunk Ang Vel (Z)',
          'Vel Hip Frontal R', 'Vel Hip Sagittal R',
          'Vel Knee R', 'Vel Ankle R',
          'Vel Hip Frontal L', 'Vel Hip Sagittal L',
          'Vel Knee L', 'Vel Ankle L',

          'Foot Pos L (X)', 'Foot Pos L (Y)', 'Foot Pos L (Z)',
          'Foot Pos R (X)', 'Foot Pos R (Y)', 'Foot Pos R (Z)',

          'GRF R', 'GRF L'
          ]

# plot figure in full screen mode (scaled down aspect ratio of my screen)
plt.rcParams['figure.figsize'] = (19.2, 10.8)

for i in range(dofs):
    subplt = plt.subplot(8,5,i+1)
    curve = step[i, :]
    plt.plot(curve)
    plt.title(f'{i} - {labels[i]}')

    # plot the derivatives to easier find corresponding velocities
    if i < 15:
        velplt = subplt.twinx()
        velplt.plot(np.gradient(curve, 1 / 250), '#aaaaaa')
        velplt.tick_params(axis='y', labelcolor='#777777')

    # remove x labels from first rows
    if i < 32:
        plt.xticks([])

plt.show()

"""
Insights:
- the first 15 dimensions are joint positions
- the next 14 the corresponding velocities
- reduced dim of velocities due to usage of quaternions for freejoints
-- rotation in quaternions is 4D, the corresponding angular velocities 3D
"""