import time
import pandas as pd
import numpy as np

CITY_DATA = { 'chicago': 'chicago.csv',
              'new york city': 'new_york_city.csv',
              'washington': 'washington.csv' }

def get_filters():
    """
    Asks user to specify a city, month, and day to analyze.

    Returns:
        (str) city - name of the city to analyze
        (str) month - name of the month to filter by, or "all" to apply no month filter
        (str) day - name of the day of week to filter by, or "all" to apply no day filter
    """
    print('Hello! Let\'s explore some US bikeshare data!')
    # TO DO: get user input for city (chicago, new york city, washington). HINT: Use a while loop to handle invalid inputs
    # Valid inputs
    valid_cities = ['chicago', 'new york city', 'washington']
    valid_months = ['january', 'february', 'march', 'april', 'may', 'june', 'all']
    valid_days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday', 'all']
    
    while True:
        city = input('Please enter the city to analyze (chicago, new york city, washington): ').lower()
        if city in valid_cities:
            break
        else:
            print('Invalid input. Please choose from: chicago, new york city, or washington.')

    # TO DO: get user input for month (all, january, february, ... , june)
    while True:
        month = input('Please enter a month to filter by (january to june), or all to apply no filter: ').lower()
        if month in valid_months:
            break
        print('Invalid month. Please choose from january to june, or all.')

    # TO DO: get user input for day of week (all, monday, tuesday, ... sunday)
    while True:
        day = input ('Please enter a day of the week to filter by, or all to apply no filter: ').lower()
        if day in valid_days:
            break
        print('Invalid day. Please choose a valid day or all.')

    print('-'*40)
    return city, month, day

def load_data(city, month, day):
    """
    Loads data for the specified city and filters by month and day if applicable.

    Args:
        (str) city - name of the city to analyze
        (str) month - name of the month to filter by, or "all" to apply no month filter
        (str) day - name of the day of week to filter by, or "all" to apply no day filter
    Returns:
        df - Pandas DataFrame containing city data filtered by month and day
    """
    # Load data file into a DataFrame
    city_data_files = {
        'chicago': '/mnt/data/chicago.csv',
        'new york city': '/mnt/data/new_york_city.csv',
        'washington': '/mnt/data/washington.csv'
    }
    df = pd.read_csv(city_data_files[city])

    # Convert the Start Time column to datetime
    df['Start Time'] = pd.to_datetime(df['Start Time'])

    # Extract month and day of week from Start Time to create new columns
    df['month'] = df['Start Time'].dt.month_name().str.lower()
    df['day_of_week'] = df['Start Time'].dt.day_name().str.lower()

    # Filter by month if applicable
    if month != 'all':
        df = df[df['month'] == month]

    # Filter by day of week if applicable
    if day != 'all':
        df = df[df['day_of_week'] == day]
    
    return df

def time_stats(df):
    """Displays statistics on the most frequent times of travel."""

    print('\nCalculating The Most Frequent Times of Travel...\n')
    start_time = time.time()

    # TO DO: display the most common month
    most_common_month = df['month'].mode()[0]
    print(f"The most common month is: {most_common_month}")
    
    # TO DO: display the most common day of week
    most_common_day = df['day_of_week'].mode()[0]
    print(f"The most common day of week is: {most_common_day}")

    # TO DO: display the most common start hour
    most_common_hour = df['Start Time'].dt.hour.mode()[0]
    print(f"The most common start hour is: {most_common_hour}")

    print("\nThis took %s seconds." % (time.time() - start_time))
    print('-'*40)


def station_stats(df):
    """Displays statistics on the most popular stations and trip."""

    print('\nCalculating The Most Popular Stations and Trip...\n')
    start_time = time.time()

    # TO DO: display most commonly used start station
    most_common_start_station = df['Start Station'].mode()[0]
    print(f"The most commonly used start station is: {most_common_start_station}")

    # TO DO: display most commonly used end station
    most_common_end_station = df['End Station'].mode()[0]
    print(f"The most commonly used end station is: {most_common_end_station}")

    # TO DO: display most frequent combination of start station and end station trip
    df['Trip'] = df['Start Station'] + " to " + df['End Station']
    most_common_trip = df['Trip'].mode()[0]
    print(f"The most frequent trip is: {most_common_trip}")


    print("\nThis took %s seconds." % (time.time() - start_time))
    print('-'*40)


def trip_duration_stats(df):
    """Displays statistics on the total and average trip duration."""

    print('\nCalculating Trip Duration...\n')
    start_time = time.time()

    # TO DO: display total travel time
    total_travel_time = df['Trip Duration'].sum()
    print(f"Total travel time: {total_travel_time} seconds")

    # TO DO: display mean travel time
    mean_travel_time = df['Trip Duration'].mean()
    print(f"Mean travel time: {mean_travel_time} seconds")

    print("\nThis took %s seconds." % (time.time() - start_time))
    print('-'*40)


def user_stats(df):
    """Displays statistics on bikeshare users."""

    print('\nCalculating User Stats...\n')
    start_time = time.time()

    # TO DO: Display counts of user types
    user_types = df['User Type'].value_counts()
    print("Counts of user types:")
    print(user_types)

    # TO DO: Display counts of gender
    if 'Gender' in df.columns:
        gender_counts = df['Gender'].value_counts()
        print("\nCounts of gender:")
        print(gender_counts)
    else:
        print("\nNo gender data available.")

    # TO DO: Display earliest, most recent, and most common year of birth
    if 'Birth Year' in df.columns:
        earliest_year = int(df['Birth Year'].min())
        most_recent_year = int(df['Birth Year'].max())
        most_common_year = int(df['Birth Year'].mode()[0])
        print("\nBirth year statistics:")
        print(f"Earliest year: {earliest_year}")
        print(f"Most recent year: {most_recent_year}")
        print(f"Most common year: {most_common_year}")
    else:
        print("\nNo birth year data available.")

    print("\nThis took %s seconds." % (time.time() - start_time))
    print('-'*40)
    
def display_data(df):
    """
    Displays 5 lines of raw data upon user request.

    Args: df - Pandas DataFrame containing the dataset
    """
    row_index = 0  # Start with the first row
    while True:
        # Chiedi all'utente se vuole vedere 5 righe di dati grezzi
        show_data = input("\nWould you like to see 5 rows of raw data? Enter yes or no: ").lower()
        
        if show_data == 'yes':
            # Mostra 5 righe di dati a partire dall'indice corrente
            print(df.iloc[row_index:row_index + 5])
            row_index += 5  # Incrementa l'indice per le prossime 5 righe
            
            # Controlla se ci sono altre righe da visualizzare
            if row_index >= len(df):
                print("\nNo more data to display.")
                break
        elif show_data == 'no':
            break
        else:
            print("\nInvalid input. Please enter 'yes' or 'no'.")

def main():
    while True:
        city, month, day = get_filters()
        df = load_data(city, month, day)

        display_data(df)
        time_stats(df)
        station_stats(df)
        trip_duration_stats(df)
        user_stats(df)
       
        restart = input('\nWould you like to restart? Enter yes or no.\n')
        if restart.lower() != 'yes':
            break

if __name__ == "__main__":
	main()
