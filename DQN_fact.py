import factory_sim as fact_sim
import numpy as np
import pandas as pd
import math 
# import matplotlib
import random
# matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
from itertools import chain
import DeepQNet
import argparse

parser = argparse.ArgumentParser(description='A tutorial of argparse!')
parser.add_argument("--s", default='/mypath/', help="path to save results")
id = str(int(np.ceil(random.random()*10000)))


args = parser.parse_args()
s = args.s
print(s)

sim_time = 5e5
WEEK = 24*7
NO_OF_WEEKS = math.ceil(sim_time/WEEK)
num_seq_steps = 20

# recipes = pd.read_csv('/mypath/recipes.csv')
# machines = pd.read_csv('/mypath/machines.csv')
recipes = pd.read_csv('C:/Users/rts/Documents/workspace/WDsim/recipes.csv')
machines = pd.read_csv('C:/Users/rts/Documents/workspace/WDsim/machines.csv')

recipes = recipes[recipes.MAXIMUMLS != 0]

# Create the machine dictionary (machine:station)
machine_d = dict()
for index, row in machines.iterrows():
    d = {row[0]:row[1]}
    machine_d.update(d)

# Modifying the above list to match the stations from the two datasets
a = machines.TOOLSET.unique()
b = recipes.TOOLSET.unique()
common_stations = (set(a) & set(b))
ls = list(common_stations)

# This dictionary has the correct set of stations
modified_machine_dict = {k: v for k, v in machine_d.items() if v in ls}

# Removing uncommon rows from recipes
for index, row in recipes.iterrows():
    if (row[2] not in ls) or (row[3] == 0 and row[4] == 0):
        recipes.drop(index, inplace=True)

recipes = recipes.dropna()
recipe_dict = dict()
for ht in list(recipes.HT.unique()):
    temp = recipes.loc[recipes['HT'] == ht]
    if len(temp) > 1:
        ls = []
        for index, row in temp.iterrows():
            ls.append([row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9]])
        d  = {ht:ls}
        recipe_dict.update(d)
    else:
        ls = []
        ls.append([row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9]])
        d = {ht:ls}
        recipe_dict.update(d)

# take only the first num_seq_steps sequence steps for each recipe to reduce the complexity of the simulation.
for ht, step in recipe_dict.items():
    recipe_dict[ht] = step[0:num_seq_steps]

# remove machines which aren't used in the first num_seq_steps for each recipe
used_stations = []
for ht in recipe_dict.keys():
    for step in recipe_dict[ht]:
        used_stations.append(step[0])

used_stations = set(used_stations)


modified_machine_dict = {k:v for k,v in modified_machine_dict.items() if v in list(used_stations)}

# Dictionary where the key is the name of the machine and the value is [station, proc_t]
# machine_dict = {'m0': 's1', 'm2': 's2', 'm1': 's1', 'm3': 's2'}
machine_dict = modified_machine_dict
print(len(machine_dict))
# recipes give the sequence of stations that must be processed at for the wafer of that head type to be completed
# recipes = {"ht1": [["s1", 5, 0]], "ht2": [["s1", 5, 0], ["s2", 5, 0]]}
recipes = recipe_dict

wafers_per_box = 4

break_mean = 1e5

repair_mean = 120

n_part_mix = 30

# average lead time for each head type
head_types = recipes.keys()
lead_dict = {}

part_mix = {}


for ht in head_types:
    d = {ht:16000}
    lead_dict.update(d)

    w = {ht:1}
    part_mix.update(w)


####################################################
########## CREATING THE STATE SPACE  ###############
####################################################
def get_state(sim):
    # Calculate the state space representation.
    # This returns a list containing the number of` parts in the factory for each combination of head type and sequence
    # step

    state_rep = sum([sim.n_HT_seq[HT] for HT in sim.recipes.keys()], [])

    # assert state_rep == state_rep2
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
    # print(len(state_rep))
    return state_rep


# Create the factory simulation object
my_sim = fact_sim.FactorySim(sim_time, machine_dict, recipes, lead_dict, wafers_per_box, part_mix, n_part_mix, break_mean=break_mean, repair_mean=repair_mean)
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

# Creating the DQN agent
dqn_agent = DeepQNet.DQN(state_space_dim= state_size, action_space= action_space, epsilon_decay=0.999, gamma=0.99)

order_count = 0
step_counter = 0
avg_reward = []
while my_sim.env.now < sim_time:
    action = dqn_agent.choose_action(state, allowed_actions)

    wafer_choice = next(wafer for wafer in my_sim.queue_lists[mach.station] if wafer.HT == action[0] and wafer.seq ==
                        action[1])

    my_sim.run_action(mach, wafer_choice)
    # print('Step Reward:' + str(my_sim.step_reward))
    # Record the machine, state, allowed actions and reward at the new time step
    next_mach = my_sim.next_machine
    next_state = get_state(my_sim)
    next_allowed_actions = my_sim.allowed_actions
    reward = my_sim.step_reward
    avg_reward.append(reward)

    # print(f"state dimension: {len(state)}")
    # print(f"next state dimension: {len(next_state)}")
    # print("action space dimension:", action_size)
    # record the information for use again in the next training example
    # mach, allowed_actions, state = next_mach, next_allowed_actions, next_state
    # print("State:", state)

    # Save the example for later training
    dqn_agent.remember(state, action, reward, next_state, next_allowed_actions)

    if my_sim.order_completed:
        # After each wafer completed, train the policy network 
        dqn_agent.replay()
        order_count += 1
        if order_count >= 1:
            # After every 20 processes update the target network and reset the order count
            dqn_agent.train_target()
            order_count = 0

    # Record the information for use again in the next training example
    mach, allowed_actions, state = next_mach, next_allowed_actions, next_state
    
    if step_counter % 1000 == 0 and step_counter > 1:
        print("Average reward: ", np.mean(avg_reward))
        avg_reward = []
        print(("%.2f" % (100*my_sim.env.now/sim_time))+"% done\n")
    step_counter += 1

# Save the trained DQN policy network
dqn_agent.save_model("DQN_model_60rm.h5")


#Wafers of each head type
print("### Wafers of each head type ###")
print("### Wafers of each head type ###")

# print(my_sim.lateness)

# print(my_sim.complete_wafer_dict)

# Total wafers produced
print("Total wafers produced:", len(my_sim.cycle_time))

# utilization
operational_times = {mach: mach.total_operational_time for mach in my_sim.machines_list}
mach_util = {mach: operational_times[mach]/sim_time for mach in my_sim.machines_list}
mean_util = {station: round(np.mean([mach_util[mach] for mach in my_sim.machines_list if mach.station == station]), 3)
             for station in my_sim.stations}
mean_mach_takt_times = {mach: np.mean(mach.takt_times) for mach in my_sim.machines_list}
std_mach_takt_times = {mach: round(np.std(mach.takt_times), 3) for mach in my_sim.machines_list}

mean_station_takt_times = {station: round(np.mean([mean_mach_takt_times[mach] for mach in my_sim.machines_list if
                                         mach.station == station and not np.isnan(mean_mach_takt_times[mach])]), 3) for
                           station in my_sim.stations}
# mean_station_takt_times = {station: round(1/sum([1/mean_mach_takt_times[mach] for mach in my_sim.machines_list if
#                                          mach.station == station]), 3) for station in my_sim.stations}

parts_per_station = {station: sum([mach.parts_made for mach in my_sim.machines_list if mach.station == station]) for
                     station in my_sim.stations}

station_wait_times = {station: np.mean(sum([my_sim.ht_seq_wait[(ht, seq)] for ht, seq in my_sim.station_HT_seq[station]], [])) for
                      station in my_sim.stations}

# stdev_util = {station: np.std(mach_util)

inter_arrival_times = {station: [t_i_plus_1 - t_i for t_i, t_i_plus_1 in zip(my_sim.arrival_times[station],
                                                    my_sim.arrival_times[station][1:])] for station in my_sim.stations}
mean_inter = {station: round(np.mean(inter_ar_ts), 3) for station, inter_ar_ts in inter_arrival_times.items()}
std_inter = {station: round(np.std(inter_ar_ts), 3) for station, inter_ar_ts in inter_arrival_times.items()}
coeff_var = {station: round(std_inter[station]/mean_inter[station], 3) for station in my_sim.stations}
machines_per_station = {station: len([mach for mach in my_sim.machines_list if mach.station == station]) for station in
                        my_sim.stations}

# print('operational times')
# print(operational_times)
# print('mean util')
# print(mean_util)
# # print(stdev_util)
# print('interarrival times')
# print(inter_arrival_times)
# print('mean interarrival')
# print(mean_inter)
# print('std inter')
# print(std_inter)
# print('coeff var')
# print(coeff_var)
# print('mean station takt times')
# print(mean_station_takt_times)

# # # Plot the time taken to complete each wafer
plt.plot(my_sim.lateness)
plt.xlabel("Wafers")
plt.ylabel("Lateness")
plt.title("The amount of time each wafer was late")
plt.show()
#
# # Plot the time taken to complete each wafer
plt.plot(my_sim.cumulative_reward_list)
plt.xlabel("step")
plt.ylabel("Cumulative Reward")
plt.title("The sum of all rewards up until each time step")
plt.show()


print(np.mean(my_sim.lateness[-1000:]))

cols = [mean_util, mean_inter, std_inter, coeff_var, mean_station_takt_times, machines_per_station, station_wait_times]
df = pd.DataFrame(cols, index=['mean_utilization', 'mean_interarrival_time', 'standard_dev_interarrival',
                  'coefficient_of_var_interarrival', 'mean_station_service_times', 'machines_per_station', 'mean_wait_time'])
df = df.transpose()
df.to_csv(s+'util'+id+'.csv')
# print(df)
with open(s+'lateness'+id+'.txt','w') as f:
  f.write('\n'.join(my_sim.lateness))









