import factory_sim as fact_sim
import numpy as np
import pandas as pd
import math 
# import matplotlib
# import random
# matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
from itertools import chain
import json
import queue
import DeepQNet
import argparse
import datetime

from predictron import Predictron, Replay_buffer

id = '{date:%Y-%m-%d-%H-%M-%S}'.format(date=datetime.datetime.now())

parser = argparse.ArgumentParser(description='A tutorial of argparse!')
parser.add_argument("--dqn_model_dir", default='./DQN_model_5e5.h5', help="Path to the DQN model")
# parser.add_argument("--predictron_model_dir", default='./Predictron_DQN_3e5_dense_32_base.h5', help="Path to the Predictron model")
parser.add_argument("--state_rep_size", default='32', help="Size of the state representation")
parser.add_argument("--sim_time", default=1e5, help="Simulation minutes")
parser.add_argument("--factory_file_dir", default='./b20_setup/', help="Path to factory setup files")
parser.add_argument("--save_dir", default='./data/', help="Path save log files in")
args = parser.parse_args()

sim_time = args.sim_time
dqn_model_dir = args.dqn_model_dir
# predictron_model_dir = args.predictron_model_dir


WEEK = 24*7
NO_OF_WEEKS = math.ceil(sim_time/WEEK)

with open(args.factory_file_dir+'break_repair_wip.json', 'r') as fp:
    break_repair_WIP = json.load(fp)

with open(args.factory_file_dir+'machines.json', 'r') as fp:
    machine_dict = json.load(fp)

with open(args.factory_file_dir+'recipes.json', 'r') as fp:
    recipes = json.load(fp)

with open(args.factory_file_dir+'due_date_lead.json', 'r') as fp:
    lead_dict = json.load(fp)

with open(args.factory_file_dir+'part_mix.json', 'r') as fp:
    part_mix = json.load(fp)

class Config_predictron():
    def __init__(self):
        self.train_dir = './ckpts/predictron_train'
        # self.num_gpus = 1
        
        # adam optimizer:
        self.learning_rate = 1e-3
        self.beta_1 = 0.9
        self.beta_2 = 0.999
        self.epsilon = 1e-8
        
        self.l2_weight=0.01
        self.dropout_rate=0.2

        self.epochs = 5000
        self.batch_size = 128
        self.episode_length = 500
        self.burnin = 3e4
        self.gamma = 0.99
        self.replay_memory_size = 100000
        self.predictron_update_steps = 50
        self.max_depth = 16
        
        self.DQN_train_steps = 5e3
        self.Predictron_train_steps = 5e3
        self.Predictron_train_steps_initial = 5e4

        self.state_rep_size = args.state_rep_size

####################################################
########## CREATING THE STATE SPACE  ###############
####################################################
def get_state(sim):
    # Calculate the state space representation.
    # This returns a list containing the number of` parts in the factory for each combination of head type and sequence
    # step
    state_rep = sum([sim.n_HT_seq[HT] for HT in sim.recipes.keys()], [])

    # print(len(state_rep))
    # b is a one-hot encoded list indicating which machine the next action will correspond to
    b = np.zeros(len(sim.machines_list))
    b[sim.machines_list.index(sim.next_machine)] = 1
    state_rep.extend(b)
    # Append the due dates list to the state space for making the decision
    rolling_window = [] # This is the rolling window that will be appended to state space
    max_length_of_window = math.ceil(max(sim.lead_dict.values()) / (7*24*60)) # Max length of the window to roll

    current_time = sim.env.now # Calculating the current time
    current_week = math.ceil(current_time / (7*24*60)) #Calculating the current week 

    for key, value in sim.due_wafers.items():
        rolling_window.append(value[current_week:current_week+max_length_of_window]) #Adding only the values from current week up till the window length
        buffer_list = [] # This list stores value of previous unfinished wafers count
        buffer_list.append(sum(value[:current_week]))
        rolling_window.extend([buffer_list])

    c = sum(rolling_window, [])
    state_rep.extend(c) # Appending the rolling window to state space
    return state_rep


# Create the factory simulation object
my_sim = fact_sim.FactorySim(sim_time, machine_dict, recipes, lead_dict, part_mix, break_repair_WIP['n_batch_wip'],
                             break_mean=break_repair_WIP['break_mean'], repair_mean=break_repair_WIP['repair_mean'])
# start the simulation
my_sim.start()
# Retrieve machine object for first action choice
mach = my_sim.next_machine
# Save the state and allowed actions at the start for later use in training examples
state = get_state(my_sim)
allowed_actions = my_sim.allowed_actions
# The action space is a list of tuples of the form [('ht1',0), ('ht1',1), ..., ('ht2', 0), ...] indicating the head
# types and sequence steps for all allowed actions.
action_space = list(chain.from_iterable(my_sim.station_HT_seq.values()))
action_size = len(action_space)
state_size = len(state)
step_counter = 0

# setup of predictron
config = Config_predictron()
config.state_size = state_size
state_queue = list([])
for i in range(config.episode_length):
    state_queue.append(np.zeros(config.state_size))
reward_queue = list(np.zeros(config.episode_length))
replay_buffer = Replay_buffer(memory_size = config.replay_memory_size)

predictron = Predictron(config)
model = predictron.model
preturn_loss_arr = []
max_preturn_loss = 0
lambda_preturn_loss_arr = []
max_lambda_preturn_loss = 0

DQN_arr =  []
predictron_lambda_arr = []
reward_episode_arr = []

# Creating the DQN agent
dqn_agent = DeepQNet.DQN(state_space_dim= state_size, action_space= action_space, epsilon_max=0., gamma=0.99)
dqn_agent.load_model(dqn_model_dir)


while my_sim.env.now < sim_time:
    action = dqn_agent.choose_action(state, allowed_actions)

    wafer_choice = next(wafer for wafer in my_sim.queue_lists[mach.station] if wafer.HT == action[0] and wafer.seq ==
                        action[1])
    
    state_episode = state_queue.pop(0)
    state_queue.append(state)
    
    my_sim.run_action(mach, wafer_choice)
    # print('Step Reward:'+ str(my_sim.step_reward))
    # Record the machine, state, allowed actions and reward at the new time step
    next_mach = my_sim.next_machine
    next_state = get_state(my_sim)
    next_allowed_actions = my_sim.allowed_actions
    reward = my_sim.step_reward
    
    reward_queue = [config.gamma*x + reward for x in reward_queue]
    reward_episode = reward_queue.pop(0)
    reward_queue.append(0.)
    
    if my_sim.env.now > config.burnin:
        step_counter += 1
        
    if step_counter > config.episode_length:
        replay_buffer.put((state_episode, reward_episode))
        if step_counter > config.episode_length+config.batch_size and (step_counter % config.predictron_update_steps) == 0:
            
            data = np.array(replay_buffer.get(config.batch_size))
            states = np.array([np.array(x) for x in data[:,0]])
            states = np.expand_dims(states,-1)
            rewards = np.array([np.array(x) for x in data[:,1]])
            rewards = np.expand_dims(rewards,-1)
            _, preturn_loss, lambda_preturn_loss = model.train_on_batch(states, rewards)
            
            max_lambda_preturn_loss = max(max_lambda_preturn_loss, lambda_preturn_loss)
            max_preturn_loss = max(max_preturn_loss, preturn_loss)
            preturn_loss_arr.append(preturn_loss)
            lambda_preturn_loss_arr.append(lambda_preturn_loss)
            
    if step_counter % 1000 == 0 and step_counter > 1:
        print(("%.2f" % (100*my_sim.env.now/sim_time))+"% done")
        
        if step_counter > config.episode_length+config.batch_size:
            print("running mean % of max preturn loss: ", "%.2f" % (100*np.mean(preturn_loss_arr[-min(10, len(preturn_loss_arr)):])/max_preturn_loss), "\t\t", np.mean(preturn_loss_arr[-min(10, len(preturn_loss_arr)):]))
            print("running mean % of max lambda preturn loss: ", "%.2f" % (100*np.mean(lambda_preturn_loss_arr[-min(10, len(lambda_preturn_loss_arr)):])/max_lambda_preturn_loss), "\t\t", np.mean(lambda_preturn_loss_arr[-min(10, len(lambda_preturn_loss_arr)):]))
            predictron_result = model.predict([state])
            DQN_arr.append(dqn_agent.calculate_value_of_action(state, allowed_actions))
            predictron_lambda_arr.append(predictron_result[1])
            reward_episode_arr.append(reward_episode)
            
            print(predictron_result[0],predictron_result[1], reward_episode, DQN_arr[-1])
        
    # print(f"state dimension: {len(state)}")
    # print(f"next state dimension: {len(next_state)}")
    # print("action space dimension:", action_size)
    # record the information for use again in the next training example
    mach, allowed_actions, state = next_mach, next_allowed_actions, next_state
    # print("State:", state)
    
# Save the trained Predictron network
model.save('./Predictron_DQN_' + str(sim_time) + '_full_' + str(args.state_rep_size) + '.h5')


plt.figure()
plt.plot(preturn_loss_arr)
plt.figure()
plt.plot(lambda_preturn_loss_arr)
plt.figure()
plt.plot(predictron_lambda_arr, label='Predictron')
plt.plot(DQN_arr, label='DQN')
plt.plot(reward_episode_arr, label='GT')
plt.title("Value estimate")
plt.legend()

predictron_error = np.abs(np.array(predictron_lambda_arr)[:,0]-np.array(reward_episode_arr))
predictron_error_avg = [predictron_error[0]]
alpha = 0.05
for i in range(len(predictron_error)-1):
    predictron_error_avg.append(predictron_error_avg[i]*(1-alpha) + predictron_error[i+1]*alpha)
DQN_error = np.abs(np.array(DQN_arr)-np.array(reward_episode_arr))
plt.figure()
plt.plot(predictron_error, label='Predictron')
plt.plot(predictron_error_avg, label='Running average')
# plt.plot(DQN_error, label='DQN')
plt.title("Absolute value estimate error")
plt.legend()

plt.figure()
plt.plot(DQN_error - predictron_error)
plt.title("DQN_error - predictron_error")



# Total wafers produced
# print("Total wafers produced:", len(my_sim.cycle_time))
# # # i = 0
# for ht in my_sim.recipes.keys():
#     # for sequ in range(len(my_sim.recipes[ht])-1):
#     # i += 1
#     # print(len(my_sim.recipes[ht]))
#     # waf = fact_sim.wafer_box(my_sim, 4, ht, my_sim.wafer_index, lead_dict, sequ)
#     # my_sim.wafer_index += 1
#     sequ = len(my_sim.recipes[ht])-1
#     print(ht)
#     print(sequ)
#     print(my_sim.get_rem_shop_time(ht, sequ, 4))

# print(my_sim.get_proc_time('ASGA', 99, 4))
# print(i)
#Wafers of each head type
print("### Wafers of each head type ###")

# print(my_sim.lateness)

print(my_sim.complete_wafer_dict)

# ht_seq_mean_w = dict()
# for tup, time_values in my_sim.ht_seq_wait.items():
#     ht_seq_mean_w[tup] = np.mean(time_values)

# with open('ht_seq_mean_wn.json', 'w') as fp:
#     json.dump({str(k): v for k,v in ht_seq_mean_w.items()}, fp)

# Total wafers produced
print("Total wafers produced:", len(my_sim.cycle_time))

# utilization
operational_times = {mach: mach.total_operational_time for mach in my_sim.machines_list}
mach_util = {mach: operational_times[mach]/sim_time for mach in my_sim.machines_list}
mean_util = {station: round(np.mean([mach_util[mach] for mach in my_sim.machines_list if mach.station == station]), 3)
             for station in my_sim.stations}
# stdev_util = {station: np.std(mach_util)

inter_arrival_times = {station: [t_i_plus_1 - t_i for t_i, t_i_plus_1 in zip(my_sim.arrival_times[station],
                                                    my_sim.arrival_times[station][1:])] for station in my_sim.stations}
mean_inter = {station: round(np.mean(inter_ar_ts), 3) for station, inter_ar_ts in inter_arrival_times.items()}
std_inter = {station: round(np.std(inter_ar_ts), 3) for station, inter_ar_ts in inter_arrival_times.items()}
coeff_var = {station: round(std_inter[station]/mean_inter[station], 3) for station in my_sim.stations}

# print(operational_times)
# print(mean_util)
# # print(stdev_util)
# print(inter_arrival_times)
# print(mean_inter)
# print(std_inter)
# print(coeff_var)
#
print(np.mean(my_sim.lateness[-10000:]))

cols = [mean_util, mean_inter, std_inter, coeff_var]
df = pd.DataFrame(cols, index=['mean_utilization', 'mean_interarrival_time', 'standard_dev_interarrival',
                  'coefficient_of_var_interarrival'])
df = df.transpose()
df.to_csv(args.save_dir+'util'+id+'.csv')
# print(df)

# # Plot the time taken to complete each wafer
plt.figure()
plt.plot(my_sim.lateness)
plt.xlabel("Wafers")
plt.ylabel("Lateness")
plt.title("The amount of time each wafer was late")
plt.show()
#
# Plot the time taken to complete each wafer
plt.plot(my_sim.cumulative_reward_list)
plt.xlabel("step")
plt.ylabel("Cumulative Reward")
plt.title("The sum of all rewards up until each time step")
plt.show()

